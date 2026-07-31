import asyncio
import shutil
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.core.config import Settings
from app.services.file_scanning import ScanResult, ScanStatus
from app.services.storage import (
    LocalStorageProvider,
    S3StorageProvider,
    StorageProvider,
    prepare_resume_upload,
    validate_storage_key,
)


class FakeScanner:
    def __init__(self, status: ScanStatus) -> None:
        self.status = status
        self.paths: list[Path] = []

    def scan(self, path: Path) -> ScanResult:
        self.paths.append(path)
        return ScanResult(self.status, "test result")


class FakeProvider(StorageProvider):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_file(self, source: Path, key: str, content_type: str) -> None:
        self.objects[validate_storage_key(key)] = source.read_bytes()

    def delete(self, key: str) -> None:
        self.objects.pop(validate_storage_key(key), None)

    def exists(self, key: str) -> bool:
        return validate_storage_key(key) in self.objects

    @contextmanager
    def materialize(self, key: str):
        raise NotImplementedError
        yield


@pytest.fixture()
def security_root():
    root = Path("storage") / f"security-test-{uuid4().hex}"
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "app_env": "development",
        "resume_quarantine_path": str(tmp_path / "quarantine"),
        "resume_storage_path": str(tmp_path / "stored"),
        "resume_scanner": "none",
        "resume_scan_policy": "allow_unavailable",
    }
    values.update(overrides)
    return Settings(
        _env_file=None,
        **values,
    )


def pdf_upload(content: bytes = b"%PDF-1.4 safe test") -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename="resume.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )


def test_clean_files_promote_with_unique_keys_and_cleanup_quarantine(
    security_root: Path,
) -> None:
    provider = FakeProvider()
    settings = make_settings(security_root)
    first = asyncio.run(
        prepare_resume_upload(
            pdf_upload(),
            provider=provider,
            scanner=FakeScanner(ScanStatus.CLEAN),
            settings=settings,
        )
    )
    second = asyncio.run(
        prepare_resume_upload(
            pdf_upload(b"%PDF-1.4 another"),
            provider=provider,
            scanner=FakeScanner(ScanStatus.CLEAN),
            settings=settings,
        )
    )
    assert first.upload_data.original_filename == second.upload_data.original_filename
    assert first.upload_data.storage_key != second.upload_data.storage_key
    first.promote()
    second.promote()
    assert len(provider.objects) == 2
    first.finish()
    second.finish()
    assert not first.quarantine_path.exists()
    assert not second.quarantine_path.exists()


def test_infected_file_is_rejected_before_storage_or_parsing(security_root: Path) -> None:
    provider = FakeProvider()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            prepare_resume_upload(
                pdf_upload(),
                provider=provider,
                scanner=FakeScanner(ScanStatus.INFECTED),
                settings=make_settings(security_root),
            )
        )
    assert caught.value.status_code == 422
    assert provider.objects == {}
    assert list((security_root / "quarantine").glob("*")) == []


def test_scanner_unavailable_policy_is_explicit_and_production_fails_closed(
    security_root: Path,
) -> None:
    provider = FakeProvider()
    allowed = asyncio.run(
        prepare_resume_upload(
            pdf_upload(),
            provider=provider,
            scanner=FakeScanner(ScanStatus.UNAVAILABLE),
            settings=make_settings(security_root),
        )
    )
    allowed.discard()

    with pytest.raises(HTTPException) as production_error:
        asyncio.run(
            prepare_resume_upload(
                pdf_upload(),
                provider=provider,
                scanner=FakeScanner(ScanStatus.UNAVAILABLE),
                settings=make_settings(security_root, app_env="production"),
            )
        )
    assert production_error.value.status_code == 503

    with pytest.raises(HTTPException) as strict_development_error:
        asyncio.run(
            prepare_resume_upload(
                pdf_upload(),
                provider=provider,
                scanner=FakeScanner(ScanStatus.ERROR),
                settings=make_settings(security_root, resume_scan_policy="fail"),
            )
        )
    assert strict_development_error.value.status_code == 503


@pytest.mark.parametrize("key", ["../secret", "/absolute/file.pdf", "safe/../../secret", "a\\b"])
def test_storage_key_rejects_path_traversal(security_root: Path, key: str) -> None:
    with pytest.raises(ValueError):
        validate_storage_key(key)
    with pytest.raises(ValueError):
        LocalStorageProvider(security_root / "stored").path_for(key)


def test_s3_provider_upload_download_and_delete(monkeypatch, security_root: Path) -> None:
    class FakeS3Client:
        def __init__(self) -> None:
            self.objects: dict[tuple[str, str], bytes] = {}

        def upload_file(self, source, bucket, key, ExtraArgs):
            self.objects[(bucket, key)] = Path(source).read_bytes()

        def download_file(self, bucket, key, destination):
            Path(destination).write_bytes(self.objects[(bucket, key)])

        def head_object(self, Bucket, Key):
            if (Bucket, Key) not in self.objects:
                raise KeyError((Bucket, Key))
            return {"ContentLength": len(self.objects[(Bucket, Key)])}

        def delete_object(self, Bucket, Key):
            self.objects.pop((Bucket, Key), None)

    client = FakeS3Client()
    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: client)
    provider = S3StorageProvider(
        bucket="resumes",
        endpoint_url="http://minio:9000",
        access_key="test",
        secret_key="test",
        secure=False,
        temp_root=security_root / "temporary",
    )
    source = security_root / "source.pdf"
    source.write_bytes(b"%PDF-1.4 provider test")
    provider.put_file(source, "resumes/one.pdf", "application/pdf")
    assert provider.exists("resumes/one.pdf") is True
    with provider.materialize("resumes/one.pdf") as downloaded:
        assert downloaded.read_bytes() == source.read_bytes()
    assert list((security_root / "temporary").glob("*")) == []
    provider.delete("resumes/one.pdf")
    assert client.objects == {}
