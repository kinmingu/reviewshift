from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import requests

from scripts.amazon_reviews_source import METADATA_FILE, REVIEW_FILES, RemoteFile

DEFAULT_OUTPUT = Path("data/raw/amazon_reviews_2023")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(remote_file: RemoteFile, output_root: Path) -> dict[str, object]:
    destination = output_root / remote_file.path
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")

    if destination.exists():
        if destination.stat().st_size != remote_file.size:
            raise RuntimeError(
                f"existing file has unexpected size: {destination} "
                f"({destination.stat().st_size} != {remote_file.size})"
            )
        return {
            "path": str(destination),
            "size": remote_file.size,
            "sha256": sha256_file(destination),
            "status": "already_present",
            "revision": remote_file.revision,
        }

    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with requests.get(
        remote_file.url, headers=headers, stream=True, timeout=120
    ) as response:
        if offset and response.status_code != 206:
            raise RuntimeError(
                f"server refused resume for {remote_file.path}; remove {partial} and retry"
            )
        response.raise_for_status()
        mode = "ab" if offset else "wb"
        with partial.open(mode) as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    if partial.stat().st_size != remote_file.size:
        raise RuntimeError(
            f"downloaded size mismatch for {remote_file.path}: "
            f"{partial.stat().st_size} != {remote_file.size}"
        )
    os.replace(partial, destination)
    return {
        "path": str(destination),
        "size": remote_file.size,
        "sha256": sha256_file(destination),
        "status": "downloaded",
        "revision": remote_file.revision,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download only the pinned Appliances review and metadata Parquet files."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--kind", choices=("all", "reviews", "metadata"), default="all"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform the transfer. Without this flag only the plan is printed.",
    )
    args = parser.parse_args()

    files = []
    if args.kind in {"all", "reviews"}:
        files.extend(REVIEW_FILES)
    if args.kind in {"all", "metadata"}:
        files.append(METADATA_FILE)
    plan = {
        "files": [
            {
                "path": item.path,
                "revision": item.revision,
                "size_bytes": item.size,
            }
            for item in files
        ],
        "total_size_bytes": sum(item.size for item in files),
        "output": str(args.output),
        "execute": args.execute,
    }
    print(json.dumps(plan, indent=2))
    if not args.execute:
        return

    results = [download_file(item, args.output) for item in files]
    manifest = {"source": "Amazon Reviews 2023", "files": results}
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "download_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

