from __future__ import annotations

import io
from dataclasses import dataclass
from urllib.parse import quote

import requests

REPOSITORY = "McAuley-Lab/Amazon-Reviews-2023"
REVIEW_REVISION = "e4458357e3499c762fb83a8c721fde557b7d0e8d"
METADATA_REVISION = "b8c2d3e0d68f6b868f96e4c6ee9ad2c4fb091522"


@dataclass(frozen=True)
class RemoteFile:
    path: str
    size: int
    revision: str

    @property
    def url(self) -> str:
        encoded_path = "/".join(quote(part) for part in self.path.split("/"))
        return (
            f"https://huggingface.co/datasets/{REPOSITORY}/resolve/"
            f"{self.revision}/{encoded_path}?download=true"
        )


REVIEW_FILES = (
    RemoteFile(
        path="raw_review_Appliances/full-00000-of-00002.parquet",
        size=203_130_070,
        revision=REVIEW_REVISION,
    ),
    RemoteFile(
        path="raw_review_Appliances/full-00001-of-00002.parquet",
        size=189_276_322,
        revision=REVIEW_REVISION,
    ),
)
METADATA_FILE = RemoteFile(
    path="raw_meta_Appliances/full-00000-of-00001.parquet",
    size=95_900_964,
    revision=METADATA_REVISION,
)


class HttpRangeReader(io.RawIOBase):
    """Seekable HTTP reader that refuses servers which ignore Range requests."""

    def __init__(
        self,
        remote_file: RemoteFile,
        *,
        max_request_bytes: int = 64 * 1024 * 1024,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__()
        self.remote_file = remote_file
        self.max_request_bytes = max_request_bytes
        self.timeout_seconds = timeout_seconds
        self.position = 0
        self.bytes_transferred = 0
        self.request_count = 0
        self.session = requests.Session()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            position = offset
        elif whence == io.SEEK_CUR:
            position = self.position + offset
        elif whence == io.SEEK_END:
            position = self.remote_file.size + offset
        else:
            raise ValueError(f"unsupported whence: {whence}")
        if position < 0:
            raise ValueError("negative seek position")
        self.position = min(position, self.remote_file.size)
        return self.position

    def read(self, size: int = -1) -> bytes:
        remaining = self.remote_file.size - self.position
        if remaining <= 0:
            return b""
        if size is None or size < 0:
            size = remaining
        size = min(size, remaining)
        if size > self.max_request_bytes:
            raise OSError(
                f"refusing a {size}-byte request; limit is {self.max_request_bytes} bytes"
            )
        start = self.position
        end = start + size - 1
        response = self.session.get(
            self.remote_file.url,
            headers={"Range": f"bytes={start}-{end}"},
            timeout=self.timeout_seconds,
        )
        if response.status_code != 206:
            raise OSError(
                "remote server did not honor Range request "
                f"({response.status_code}); refusing a full-file transfer"
            )
        content = response.content
        if len(content) != size:
            raise OSError(f"expected {size} bytes, received {len(content)}")
        self.position += len(content)
        self.bytes_transferred += len(content)
        self.request_count += 1
        return content

    def readinto(self, buffer: bytearray) -> int:
        content = self.read(len(buffer))
        buffer[: len(content)] = content
        return len(content)

    def close(self) -> None:
        self.session.close()
        super().close()

