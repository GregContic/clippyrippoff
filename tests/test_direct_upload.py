from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import backend.services.direct_upload as direct_upload
from backend.schemas import AnalyzeResponse
from backend.services.storage import ClientError, S3Storage, StorageSettings


class _Body:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def read(self) -> bytes:
        return self.value


class _R2Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}
        self.multipart: dict[str, dict[str, object]] = {}
        self.presigned: list[tuple[str, dict[str, object], int]] = []

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presigned.append((operation, Params, ExpiresIn))
        return f"https://r2.example/{operation}/{Params['Key']}?expires={ExpiresIn}"

    def create_multipart_upload(self, Bucket, Key, ContentType):
        upload_id = f"multipart-{len(self.multipart) + 1}"
        self.multipart[upload_id] = {
            "key": Key,
            "content_type": ContentType,
            "parts": {},
        }
        return {"UploadId": upload_id}

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):
        session = self.multipart.pop(UploadId)
        parts = session["parts"]
        body = b"".join(parts[part["PartNumber"]] for part in MultipartUpload["Parts"])
        self.objects[Key] = {"body": body, "content_type": session["content_type"]}

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.multipart.pop(UploadId, None)

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            try:
                error = ClientError({"Error": {"Code": "404"}}, "HeadObject")
            except TypeError:
                error = ClientError()
            if not hasattr(error, "response"):
                error.response = {"Error": {"Code": "404"}}
            raise error
        obj = self.objects[Key]
        return {"ContentLength": len(obj["body"]), "ContentType": obj["content_type"]}

    def get_object(self, Bucket, Key):
        return {"Body": _Body(self.objects[Key]["body"])}

    def put_object(self, Bucket, Key, Body, ContentType=None, **kwargs):
        self.objects[Key] = {"body": Body, "content_type": ContentType}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def list_objects_v2(self, Bucket, Prefix):
        return {"Contents": [{"Key": key} for key in self.objects if key.startswith(Prefix)]}

    def upload_fileobj(self, stream, bucket, key, ExtraArgs=None):
        self.objects[key] = {
            "body": stream.read(),
            "content_type": (ExtraArgs or {}).get("ContentType"),
        }

    def download_fileobj(self, bucket, key, stream):
        stream.write(self.objects[key]["body"])


class TestDirectUpload(unittest.TestCase):
    def setUp(self) -> None:
        self.client = _R2Client()
        settings = StorageSettings("r2", Path("processing/temp"), "private", "endpoint", "access", "secret")
        self.backend = S3Storage(settings, client=self.client)
        self.storage_patch = patch.object(direct_upload, "storage", self.backend)
        self.storage_patch.start()
        self.env_patch = patch.dict(
            "os.environ",
            {
                "MAX_UPLOAD_BYTES": str(12 * 1024 * 1024),
                "R2_MULTIPART_THRESHOLD_BYTES": str(100 * 1024 * 1024),
                "R2_MULTIPART_PART_SIZE_BYTES": str(5 * 1024 * 1024),
                "R2_UPLOAD_URL_TTL_SECONDS": "120",
                "R2_UPLOAD_SESSION_TTL_SECONDS": "600",
            },
        )
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.storage_patch.stop()

    def test_rejects_oversized_invalid_extension_and_mismatched_content_type(self) -> None:
        with self.assertRaises(direct_upload.UploadServiceError) as oversized:
            direct_upload.start_upload("clip.mp4", 12 * 1024 * 1024 + 1, "video/mp4", "owner-a")
        self.assertEqual(oversized.exception.status_code, 413)

        with self.assertRaises(direct_upload.UploadServiceError) as extension:
            direct_upload.start_upload("document.txt", 10, "application/octet-stream", "owner-a")
        self.assertEqual(extension.exception.status_code, 400)

        with self.assertRaises(direct_upload.UploadServiceError) as content_type:
            direct_upload.start_upload("clip.mp4", 10, "video/webm", "owner-a")
        self.assertEqual(content_type.exception.status_code, 400)

    def test_presigned_put_is_short_lived_and_session_is_owner_scoped(self) -> None:
        upload = direct_upload.start_upload("clip.mp4", 8, "video/mp4", "owner-a")
        self.assertEqual(upload["upload_mode"], "put")
        self.assertEqual(self.client.presigned[-1][0], "put_object")
        self.assertEqual(self.client.presigned[-1][2], 120)

        with self.assertRaises(direct_upload.UploadServiceError) as wrong_owner:
            direct_upload.single_upload_url(upload["upload_id"], "owner-b")
        self.assertEqual(wrong_owner.exception.status_code, 404)

    def test_completion_verifies_object_size_and_registers_analysis_idempotently(self) -> None:
        upload = direct_upload.start_upload("clip.mp4", 8, "video/mp4", "owner-a")
        object_key = f"uploads/pending/{upload['upload_id']}/clip.mp4"
        self.client.objects[object_key] = {"body": b"12345678", "content_type": "video/mp4"}
        response = AnalyzeResponse(video_id=upload["video_id"], status="queued", job_id="job-1")

        with patch(
            "backend.services.analysis_service.start_stored_upload_analysis",
            return_value=response,
        ) as start_analysis:
            result = direct_upload.complete_upload(upload["upload_id"], "owner-a", [])
            repeated = direct_upload.complete_upload(upload["upload_id"], "owner-a", [])

        self.assertEqual(result, repeated)
        start_analysis.assert_called_once_with(
            upload["video_id"],
            object_key,
            filename="clip.mp4",
            owner_id="owner-a",
            size_bytes=8,
        )
        self.assertEqual(result["job_id"], "job-1")

    def test_completion_rejects_and_removes_wrong_size_object(self) -> None:
        upload = direct_upload.start_upload("clip.mp4", 8, "video/mp4", "owner-a")
        object_key = f"uploads/pending/{upload['upload_id']}/clip.mp4"
        self.client.objects[object_key] = {"body": b"short", "content_type": "video/mp4"}

        with self.assertRaises(direct_upload.UploadServiceError) as mismatch:
            direct_upload.complete_upload(upload["upload_id"], "owner-a", [])
        self.assertEqual(mismatch.exception.status_code, 400)
        self.assertNotIn(object_key, self.client.objects)

    def test_completion_rejects_mismatched_stored_content_type(self) -> None:
        upload = direct_upload.start_upload("clip.mp4", 8, "video/mp4", "owner-a")
        object_key = f"uploads/pending/{upload['upload_id']}/clip.mp4"
        self.client.objects[object_key] = {"body": b"12345678", "content_type": "video/webm"}

        with self.assertRaises(direct_upload.UploadServiceError) as mismatch:
            direct_upload.complete_upload(upload["upload_id"], "owner-a", [])
        self.assertEqual(mismatch.exception.status_code, 400)
        self.assertNotIn(object_key, self.client.objects)

    def test_multipart_requires_every_part_and_retries_with_fresh_urls(self) -> None:
        self.env_patch.stop()
        self.env_patch = patch.dict(
            "os.environ",
            {
                "MAX_UPLOAD_BYTES": str(12 * 1024 * 1024),
                "R2_MULTIPART_THRESHOLD_BYTES": "1",
                "R2_MULTIPART_PART_SIZE_BYTES": str(5 * 1024 * 1024),
                "R2_UPLOAD_URL_TTL_SECONDS": "120",
                "R2_UPLOAD_SESSION_TTL_SECONDS": "600",
            },
        )
        self.env_patch.start()

        size = 5 * 1024 * 1024 + 1
        upload = direct_upload.start_upload("clip.mp4", size, "video/mp4", "owner-a")
        self.assertEqual(upload["upload_mode"], "multipart")
        with self.assertRaises(direct_upload.UploadServiceError) as wrong_owner:
            direct_upload.part_upload_url(upload["upload_id"], "owner-b", 1)
        self.assertEqual(wrong_owner.exception.status_code, 404)
        url_one = direct_upload.part_upload_url(upload["upload_id"], "owner-a", 1)
        url_two = direct_upload.part_upload_url(upload["upload_id"], "owner-a", 1)
        self.assertNotEqual(url_one, "")
        self.assertNotEqual(url_two, "")
        multipart_id = next(iter(self.client.multipart))
        parts = self.client.multipart[multipart_id]["parts"]
        parts[1] = b"a" * (5 * 1024 * 1024)
        parts[2] = b"b"
        object_key = f"uploads/pending/{upload['upload_id']}/clip.mp4"

        with self.assertRaises(direct_upload.UploadServiceError) as incomplete:
            direct_upload.complete_upload(upload["upload_id"], "owner-a", [{"part_number": 1, "etag": "etag-1"}])
        self.assertEqual(incomplete.exception.status_code, 400)
        self.assertIn(multipart_id, self.client.multipart)

        with patch(
            "backend.services.analysis_service.start_stored_upload_analysis",
            return_value=AnalyzeResponse(video_id=upload["video_id"], status="queued"),
        ):
            result = direct_upload.complete_upload(
                upload["upload_id"],
                "owner-a",
                [
                    {"part_number": 2, "etag": "etag-2"},
                    {"part_number": 1, "etag": "etag-1"},
                ],
            )
        self.assertEqual(result["video_id"], upload["video_id"])
        self.assertEqual(len(self.client.objects[object_key]["body"]), size)
        self.assertEqual(self.client.presigned[-1][2], 120)

    def test_cancel_and_expiry_abort_incomplete_uploads(self) -> None:
        self.env_patch.stop()
        self.env_patch = patch.dict(
            "os.environ",
            {
                "MAX_UPLOAD_BYTES": str(12 * 1024 * 1024),
                "R2_MULTIPART_THRESHOLD_BYTES": "1",
                "R2_MULTIPART_PART_SIZE_BYTES": str(5 * 1024 * 1024),
                "R2_UPLOAD_URL_TTL_SECONDS": "120",
                "R2_UPLOAD_SESSION_TTL_SECONDS": "600",
            },
        )
        self.env_patch.start()

        canceled = direct_upload.start_upload("cancel.mp4", 5 * 1024 * 1024, "video/mp4", "owner-a")
        canceled_multipart_id = next(iter(self.client.multipart))
        direct_upload.cancel_upload(canceled["upload_id"], "owner-a")
        self.assertNotIn(canceled_multipart_id, self.client.multipart)

        expired = direct_upload.start_upload("expired.mp4", 5 * 1024 * 1024, "video/mp4", "owner-a")
        expired_multipart_id = next(iter(self.client.multipart))
        session_key = f"uploads/sessions/{expired['upload_id']}.json"
        session = json.loads(self.backend.get_bytes(session_key))
        session["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.backend.put_bytes(session_key, json.dumps(session).encode(), "application/json")
        self.assertEqual(direct_upload.cleanup_expired_uploads(), 1)
        self.assertNotIn(expired_multipart_id, self.client.multipart)

    def test_canceled_put_keeps_tombstone_to_clean_late_object(self) -> None:
        upload = direct_upload.start_upload("clip.mp4", 8, "video/mp4", "owner-a")
        object_key = f"uploads/pending/{upload['upload_id']}/clip.mp4"
        direct_upload.cancel_upload(upload["upload_id"], "owner-a")
        session_key = f"uploads/sessions/{upload['upload_id']}.json"
        session = json.loads(self.backend.get_bytes(session_key))
        self.assertEqual(session["status"], "canceled")

        with self.assertRaises(direct_upload.UploadServiceError) as canceled:
            direct_upload.single_upload_url(upload["upload_id"], "owner-a")
        self.assertEqual(canceled.exception.status_code, 410)

        self.client.objects[object_key] = {"body": b"late put", "content_type": "video/mp4"}
        session["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.backend.put_bytes(session_key, json.dumps(session).encode(), "application/json")
        self.assertEqual(direct_upload.cleanup_expired_uploads(), 1)
        self.assertNotIn(object_key, self.client.objects)

    def test_cancel_rejects_upload_already_handed_to_analysis(self) -> None:
        upload = direct_upload.start_upload("processing.mp4", 8, "video/mp4", "owner-a")
        session_key = f"uploads/sessions/{upload['upload_id']}.json"
        session = json.loads(self.backend.get_bytes(session_key))
        session["status"] = "uploaded"
        self.backend.put_bytes(session_key, json.dumps(session).encode(), "application/json")

        with self.assertRaises(direct_upload.UploadServiceError) as error:
            direct_upload.cancel_upload(upload["upload_id"], "owner-a")

        self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
