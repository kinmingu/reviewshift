from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import requests

REPOSITORY = "McAuley-Lab/Amazon-Reviews-2023"
TreeKind = Literal["reviews", "metadata"]


@dataclass(frozen=True)
class SourcePart:
    revision: str
    directory: str
    expected_file_count: int
    expected_size_bytes: int


@dataclass(frozen=True)
class CategorySource:
    source_name: str
    korean_name: str
    reviews: SourcePart
    metadata: SourcePart


@dataclass(frozen=True)
class RemoteParquet:
    path: str
    size: int
    revision: str
    sha256: str | None

    @property
    def url(self) -> str:
        encoded_path = "/".join(quote(part) for part in self.path.split("/"))
        return (
            f"https://huggingface.co/datasets/{REPOSITORY}/resolve/"
            f"{self.revision}/{encoded_path}?download=true"
        )


# 카테고리명은 공식 배포 이름을 그대로 사용한다. 화면용 한국어 이름과 원천 키를
# 분리해야 번역이 바뀌어도 잘못된 원천 파일을 읽지 않는다.
CATEGORY_SOURCES: dict[str, CategorySource] = {
    "Electronics": CategorySource(
        source_name="Electronics",
        korean_name="전자제품",
        reviews=SourcePart(
            revision="758b2e8f09ca2239eeac8fb9cd9ea83d19785f7a",
            directory="raw_review_Electronics",
            expected_file_count=34,
            expected_size_bytes=9_661_010_652,
        ),
        metadata=SourcePart(
            revision="3c9f864b83420edc8a9d8e5dc19c14c46eaf6c3b",
            directory="raw_meta_Electronics",
            expected_file_count=10,
            expected_size_bytes=1_963_147_732,
        ),
    ),
    "Beauty_and_Personal_Care": CategorySource(
        source_name="Beauty_and_Personal_Care",
        korean_name="뷰티·개인관리",
        reviews=SourcePart(
            revision="e4458357e3499c762fb83a8c721fde557b7d0e8d",
            directory="raw_review_Beauty_and_Personal_Care",
            expected_file_count=16,
            expected_size_bytes=4_372_257_802,
        ),
        metadata=SourcePart(
            revision="3c9f864b83420edc8a9d8e5dc19c14c46eaf6c3b",
            directory="raw_meta_Beauty_and_Personal_Care",
            expected_file_count=5,
            expected_size_bytes=1_060_447_218,
        ),
    ),
    "Cell_Phones_and_Accessories": CategorySource(
        source_name="Cell_Phones_and_Accessories",
        korean_name="휴대폰·액세서리",
        reviews=SourcePart(
            revision="758b2e8f09ca2239eeac8fb9cd9ea83d19785f7a",
            directory="raw_review_Cell_Phones_and_Accessories",
            expected_file_count=14,
            expected_size_bytes=3_749_055_882,
        ),
        metadata=SourcePart(
            revision="3c9f864b83420edc8a9d8e5dc19c14c46eaf6c3b",
            directory="raw_meta_Cell_Phones_and_Accessories",
            expected_file_count=7,
            expected_size_bytes=1_267_381_198,
        ),
    ),
    "Home_and_Kitchen": CategorySource(
        source_name="Home_and_Kitchen",
        korean_name="주방·생활용품",
        reviews=SourcePart(
            revision="758b2e8f09ca2239eeac8fb9cd9ea83d19785f7a",
            directory="raw_review_Home_and_Kitchen",
            expected_file_count=45,
            expected_size_bytes=12_323_721_678,
        ),
        metadata=SourcePart(
            revision="3c9f864b83420edc8a9d8e5dc19c14c46eaf6c3b",
            directory="raw_meta_Home_and_Kitchen",
            expected_file_count=21,
            expected_size_bytes=4_421_906_660,
        ),
    ),
    "Sports_and_Outdoors": CategorySource(
        source_name="Sports_and_Outdoors",
        korean_name="스포츠·아웃도어",
        reviews=SourcePart(
            revision="758b2e8f09ca2239eeac8fb9cd9ea83d19785f7a",
            directory="raw_review_Sports_and_Outdoors",
            expected_file_count=14,
            expected_size_bytes=3_900_461_924,
        ),
        metadata=SourcePart(
            revision="3c9f864b83420edc8a9d8e5dc19c14c46eaf6c3b",
            directory="raw_meta_Sports_and_Outdoors",
            expected_file_count=8,
            expected_size_bytes=1_560_973_524,
        ),
    ),
    "Toys_and_Games": CategorySource(
        source_name="Toys_and_Games",
        korean_name="장난감·게임",
        reviews=SourcePart(
            revision="758b2e8f09ca2239eeac8fb9cd9ea83d19785f7a",
            directory="raw_review_Toys_and_Games",
            expected_file_count=11,
            expected_size_bytes=2_897_168_130,
        ),
        metadata=SourcePart(
            revision="3c9f864b83420edc8a9d8e5dc19c14c46eaf6c3b",
            directory="raw_meta_Toys_and_Games",
            expected_file_count=5,
            expected_size_bytes=976_331_043,
        ),
    ),
    "Health_and_Household": CategorySource(
        source_name="Health_and_Household",
        korean_name="건강·가정용품",
        reviews=SourcePart(
            revision="758b2e8f09ca2239eeac8fb9cd9ea83d19785f7a",
            directory="raw_review_Health_and_Household",
            expected_file_count=16,
            expected_size_bytes=4_703_100_699,
        ),
        metadata=SourcePart(
            revision="3c9f864b83420edc8a9d8e5dc19c14c46eaf6c3b",
            directory="raw_meta_Health_and_Household",
            expected_file_count=5,
            expected_size_bytes=937_950_622,
        ),
    ),
}


def list_remote_files(source: CategorySource, kind: TreeKind) -> list[RemoteParquet]:
    part = source.reviews if kind == "reviews" else source.metadata
    api_url = (
        f"https://huggingface.co/api/datasets/{REPOSITORY}/tree/"
        f"{part.revision}/{part.directory}?recursive=false&expand=true"
    )
    response = requests.get(api_url, timeout=60)
    response.raise_for_status()
    items = response.json()
    files = [
        RemoteParquet(
            path=item["path"],
            size=int(item["size"]),
            revision=part.revision,
            sha256=(item.get("lfs") or {}).get("oid"),
        )
        for item in items
        if item.get("type") == "file" and item["path"].endswith(".parquet")
    ]
    files.sort(key=lambda item: item.path)

    # 저장소 구성이 바뀌었는데도 그대로 다운로드하면 재현성이 깨진다. 고정 리비전의
    # 파일 수와 합계가 사전 조사값과 다르면 전송 전에 즉시 중단한다.
    actual_size = sum(item.size for item in files)
    if len(files) != part.expected_file_count or actual_size != part.expected_size_bytes:
        raise RuntimeError(
            f"source manifest mismatch for {source.source_name}/{kind}: "
            f"files={len(files)}, bytes={actual_size}"
        )
    return files
