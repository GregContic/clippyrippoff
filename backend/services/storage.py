from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class StorageError(RuntimeError):
    """Raised when configured object storage cannot complete an operation."""


@dataclass(frozen=True)
class StorageSettings:
    backend: str
    temp_dir: Path
    bucket: str | None = None
    endpoint_url: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    account_id: str | None = None

    @classmethod
    def from_environment(cls) -> "StorageSettings":
        backend = os.getenv("STORAGE_BACKEND", "local").strip().lower() or "local"
        if backend not in {"local", "r2", "s3"}:
            raise StorageError("STORAGE_BACKEND must be 'local' or 'r2'.")
        temp_dir = Path(os.getenv("TEMP_DIR", "processing/temp")).expanduser()
        return cls(
            backend=backend,
            temp_dir=temp_dir,
            bucket=os.getenv("R2_BUCKET_NAME"),
            endpoint_url=os.getenv("R2_ENDPOINT_URL"),
            access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
            secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
            account_id=os.getenv("R2_ACCOUNT_ID"),
        )


class StorageBackend:
    def upload_file(self, source: Path, key: str, content_type: str | None = None) -> None:
        raise NotImplementedError

    def download_file(self, key: str, destination: Path) -> None:
        raise NotImplementedError

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        raise NotImplementedError

    def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def presign(self, key: str, expires: int = 300) -> str | None:
        return None

    def list_keys(self, prefix: str) -> Iterable[str]:
        return ()

    def open_stream(self, key: str):
        raise NotImplementedError


class LocalStorage(StorageBackend):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise StorageError("Invalid storage key.")
        return path

    def upload_file(self, source: Path, key: str, content_type: str | None = None) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    def download_file(self, key: str, destination: Path) -> None:
        source = self._path(key)
        if not source.is_file():
            raise FileNotFoundError(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list_keys(self, prefix: str) -> Iterable[str]:
        base = self._path(prefix)
        if not base.exists():
            return ()
        return (str(path.relative_to(self.root)).replace("\\", "/") for path in base.rglob("*") if path.is_file())

    def open_stream(self, key: str):
        return self._path(key).open("rb")


class S3Storage(StorageBackend):
    def __init__(self, settings: StorageSettings, client: object | None = None) -> None:
        if not all((settings.bucket, settings.endpoint_url, settings.access_key_id, settings.secret_access_key)):
            raise StorageError("R2 configuration requires bucket, endpoint, access key, and secret key.")
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise StorageError("boto3 is required when STORAGE_BACKEND is r2.") from exc
        self.bucket = settings.bucket
        if client is not None:
            self.client = client
        else:
            self.client = boto3.client(
                "s3",
                endpoint_url=settings.endpoint_url,
                aws_access_key_id=settings.access_key_id,
                aws_secret_access_key=settings.secret_access_key,
                region_name="auto",
            )

    def upload_file(self, source: Path, key: str, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        with source.open("rb") as stream:
            self.client.upload_fileobj(stream, self.bucket, key, ExtraArgs=extra)

    def download_file(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as stream:
            self.client.download_fileobj(self.bucket, key, stream)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.ClientError:
            return False
        return True

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def presign(self, key: str, expires: int = 300) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires
        )

    def list_keys(self, prefix: str) -> Iterable[str]:
        response = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        return (item["Key"] for item in response.get("Contents", []))

    def open_stream(self, key: str):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]


def get_storage() -> StorageBackend:
    settings = StorageSettings.from_environment()
    if settings.backend == "local":
        return LocalStorage(settings.temp_dir.parent.parent)
    return S3Storage(settings)


storage = get_storage()
