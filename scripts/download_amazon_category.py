"""Amazon Reviews 2023 카테고리 원본 Parquet 파일을 data/ 폴더로 내려받습니다(해시 검증 포함)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from scripts.amazon_category_sources import (
    CATEGORY_SOURCES,
    CategorySource,
    RemoteParquet,
    list_remote_files,
)

DEFAULT_OUTPUT = Path("data/raw/amazon_reviews_2023")


# 파일의 SHA-256 해시(내려받은 파일이 온전한지 확인).
def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 파일 하나를 내려받습니다(이미 있고 해시가 맞으면 건너뜀).
def _download_file(remote: RemoteParquet, output_root: Path) -> dict[str, object]:
    destination = output_root / remote.path
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")

    if destination.exists():
        if destination.stat().st_size != remote.size:
            raise RuntimeError(f"기존 파일 크기가 원천과 다릅니다: {destination}")
        actual_hash = _sha256_file(destination)
        if remote.sha256 and actual_hash != remote.sha256:
            raise RuntimeError(f"기존 파일 SHA-256이 원천과 다릅니다: {destination}")
        return {
            "path": str(destination),
            "size_bytes": remote.size,
            "sha256": actual_hash,
            "status": "already_present",
        }

    # 중간 파일은 그대로 남겨 두고 curl의 Range 요청으로 이어받는다.
    # Python requests가 Xet CDN 본문에서 정지하는 환경이 있어, Windows에 기본
    # 포함된 curl을 전송 전용으로 쓰고 검증은 다시 Python에서 수행한다.
    offset = partial.stat().st_size if partial.exists() else 0
    print(
        f"다운로드 시작: {remote.path} "
        f"({offset:,}/{remote.size:,} bytes에서 재개)",
        flush=True,
    )
    subprocess.run(
        [
            "curl.exe",
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--retry",
            "5",
            "--retry-all-errors",
            "--continue-at",
            "-",
            "--output",
            str(partial),
            remote.url,
        ],
        check=True,
    )

    if partial.stat().st_size != remote.size:
        raise RuntimeError(
            f"다운로드 크기가 다릅니다: {partial.stat().st_size} != {remote.size}"
        )
    actual_hash = _sha256_file(partial)
    if remote.sha256 and actual_hash != remote.sha256:
        raise RuntimeError(f"다운로드 SHA-256이 원천과 다릅니다: {remote.path}")
    os.replace(partial, destination)
    print(f"다운로드 완료: {remote.path}", flush=True)
    return {
        "path": str(destination),
        "size_bytes": remote.size,
        "sha256": actual_hash,
        "status": "downloaded",
    }


# 내려받을 파일 목록(리뷰/상품정보/둘 다).
def _plan(source: CategorySource, kind: str) -> list[RemoteParquet]:
    files: list[RemoteParquet] = []
    if kind in {"all", "reviews"}:
        files.extend(list_remote_files(source, "reviews"))
    if kind in {"all", "metadata"}:
        files.extend(list_remote_files(source, "metadata"))
    return files


# 명령행 옵션으로 카테고리를 받아 다운로드를 실행합니다.
def main() -> None:
    parser = argparse.ArgumentParser(
        description="고정 리비전의 Amazon Reviews 2023 카테고리 Parquet를 받습니다."
    )
    parser.add_argument("--category", choices=sorted(CATEGORY_SOURCES), required=True)
    parser.add_argument(
        "--kind", choices=("all", "reviews", "metadata"), default="all"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="동시에 받을 파일 수입니다. 기본값 4는 회선과 디스크 부담을 제한한 값입니다.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="지정하지 않으면 다운로드 없이 파일 수와 용량만 확인합니다.",
    )
    args = parser.parse_args()

    source = CATEGORY_SOURCES[args.category]
    files = _plan(source, args.kind)
    plan = {
        "category": source.source_name,
        "korean_name": source.korean_name,
        "file_count": len(files),
        "total_size_bytes": sum(item.size for item in files),
        "total_size_gib": round(sum(item.size for item in files) / 2**30, 2),
        "execute": args.execute,
        "output": str(args.output),
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if not args.execute:
        return
    if args.workers < 1 or args.workers > 8:
        raise ValueError("--workers는 1~8 사이여야 합니다.")

    # 파일 단위 병렬화라서 각 작업은 서로 다른 .part 파일만 수정합니다. 이미 받은 바이트는
    # curl의 Range 재개 기능으로 보존하며, 최종 파일은 SHA-256 검증 뒤에만 확정합니다.
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(_download_file, item, args.output): item for item in files
        }
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: str(item["path"]))
    manifest = {
        **plan,
        "review_revision": source.reviews.revision,
        "metadata_revision": source.metadata.revision,
        "files": results,
    }
    manifest_path = args.output / f"download_manifest_{source.source_name}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"검증 manifest 저장: {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
