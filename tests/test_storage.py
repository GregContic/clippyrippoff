import tempfile
import unittest
from pathlib import Path

from backend.services.storage import LocalStorage, S3Storage, StorageSettings


class FakeBody:
    def __init__(self, value: bytes):
        self.value = value

    def read(self) -> bytes:
        return self.value


class FakeS3:
    class exceptions:
        class ClientError(Exception):
            pass

    def __init__(self):
        self.objects = {}

    def upload_fileobj(self, stream, bucket, key, ExtraArgs=None):
        self.objects[key] = stream.read()

    def download_fileobj(self, bucket, key, stream):
        stream.write(self.objects[key])

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        return {"Body": FakeBody(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise self.exceptions.ClientError()

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return f"https://example.test/{Params['Key']}?expires={ExpiresIn}"

    def list_objects_v2(self, Bucket, Prefix):
        return {"Contents": [{"Key": key} for key in self.objects if key.startswith(Prefix)]}


class TestStorage(unittest.TestCase):
    def test_s3_transfers_stream_through_mock_client(self):
        settings = StorageSettings("r2", Path("processing/temp"), "bucket", "endpoint", "key", "secret")
        backend = S3Storage(settings, client=FakeS3())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            destination = Path(directory) / "copy.mp4"
            source.write_bytes(b"large media fixture")
            backend.upload_file(source, "videos/source.mp4")
            backend.download_file("videos/source.mp4", destination)
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertTrue(backend.exists("videos/source.mp4"))
            self.assertTrue(backend.presign("videos/source.mp4").startswith("https://"))

    def test_local_backend_keeps_keys_private_to_root(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = LocalStorage(Path(directory))
            source = Path(directory) / "source.txt"
            source.write_text("ok", encoding="utf-8")
            backend.upload_file(source, "objects/source.txt")
            self.assertEqual(backend.get_bytes("objects/source.txt"), b"ok")
