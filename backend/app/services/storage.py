import hashlib
import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, UploadFile, status

from app.core.config import Settings, get_settings
from app.services.applications import ResumeUploadData
from app.services.file_scanning import (
    ClamAVScanner,
    FileScanner,
    ScanStatus,
    UnavailableScanner,
)

ALLOWED_RESUMES = {
    ".pdf": {"application/pdf"},
    ".doc": {"application/msword", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
}


def validate_storage_key(key: str) -> str:
    if not key or "\\" in key:
        raise ValueError("Invalid storage key")
    path = PurePosixPath(key)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Invalid storage key")
    return path.as_posix()


class StorageProvider(ABC):
    @abstractmethod
    def put_file(self, source: Path, key: str, content_type: str) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def materialize(self, key: str) -> Iterator[Path]: ...


class LocalStorageProvider(StorageProvider):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        safe_key = validate_storage_key(key)
        path = (self.root / Path(*PurePosixPath(safe_key).parts)).resolve()
        if self.root not in path.parents:
            raise ValueError("Storage path escapes configured root")
        return path

    def put_file(self, source: Path, key: str, content_type: str) -> None:
        destination = self.path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)

    def delete(self, key: str) -> None:
        self.path_for(key).unlink(missing_ok=True)

    @contextmanager
    def materialize(self, key: str) -> Iterator[Path]:
        path = self.path_for(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        yield path


class S3StorageProvider(StorageProvider):
    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool = True,
        temp_root: Path | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("S3 bucket is required")
        import boto3

        self.bucket = bucket
        self.temp_root = (temp_root or Path("./storage/quarantine")).resolve()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            use_ssl=secure,
        )

    def put_file(self, source: Path, key: str, content_type: str) -> None:
        safe_key = validate_storage_key(key)
        self.client.upload_file(
            str(source), self.bucket, safe_key, ExtraArgs={"ContentType": content_type}
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=validate_storage_key(key))

    @contextmanager
    def materialize(self, key: str) -> Iterator[Path]:
        safe_key = validate_storage_key(key)
        suffix = PurePosixPath(safe_key).suffix
        with NamedTemporaryFile(suffix=suffix, delete=False, dir=self.temp_root) as temporary:
            path = Path(temporary.name)
        try:
            self.client.download_file(self.bucket, safe_key, str(path))
            yield path
        finally:
            path.unlink(missing_ok=True)


@dataclass
class PreparedResumeUpload:
    upload_data: ResumeUploadData
    quarantine_path: Path
    provider: StorageProvider
    promoted: bool = False

    def promote(self) -> Path:
        if not self.promoted:
            self.promoted = True
            try:
                self.provider.put_file(
                    self.quarantine_path, self.upload_data.storage_key, self.upload_data.mime
                )
            except Exception:
                try:
                    self.provider.delete(self.upload_data.storage_key)
                finally:
                    self.promoted = False
                raise
        return self.quarantine_path

    def finish(self) -> None:
        self.quarantine_path.unlink(missing_ok=True)

    def discard(self) -> None:
        try:
            if self.promoted:
                self.provider.delete(self.upload_data.storage_key)
        finally:
            self.quarantine_path.unlink(missing_ok=True)


def validate_file_signature(path: Path, suffix: str) -> None:
    with path.open("rb") as stored_file:
        header = stored_file.read(8)
    valid = False
    if suffix == ".pdf":
        valid = header.startswith(b"%PDF-")
    elif suffix == ".doc":
        # Legacy Word files are OLE2 compound documents. The 8-byte OLE2 magic alone is a
        # weak signal -- xls/ppt/msi share it -- so also require the "WordDocument" stream
        # (stored UTF-16LE in the compound-file directory) that every genuine .doc carries.
        # This is only a last line of defense; the malware scanner (enforce_scan_policy) is
        # the real guarantee for uploaded content.
        if header.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            with path.open("rb") as ole_document:
                body = ole_document.read()
            valid = "WordDocument".encode("utf-16-le") in body
    elif suffix == ".docx" and header.startswith(b"PK"):
        try:
            with ZipFile(path) as archive:
                names = set(archive.namelist())
                valid = "[Content_Types].xml" in names and "word/document.xml" in names
        except BadZipFile:
            valid = False
    if not valid:
        raise HTTPException(status_code=415, detail="File content does not match its extension")


def get_storage_provider(settings: Settings | None = None) -> StorageProvider:
    settings = settings or get_settings()
    if settings.resume_storage_provider == "local":
        return LocalStorageProvider(Path(settings.resume_storage_path))
    if settings.resume_storage_provider == "s3":
        return S3StorageProvider(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=settings.s3_secure,
            temp_root=Path(settings.resume_quarantine_path),
        )
    raise RuntimeError(f"Unsupported storage provider: {settings.resume_storage_provider}")


def get_file_scanner(settings: Settings | None = None) -> FileScanner:
    settings = settings or get_settings()
    if settings.resume_scanner == "clamav":
        return ClamAVScanner(settings.clamav_host, settings.clamav_port, settings.clamav_timeout)
    if settings.resume_scanner == "none":
        return UnavailableScanner()
    raise RuntimeError(f"Unsupported scanner: {settings.resume_scanner}")


def enforce_scan_policy(scan_status: ScanStatus, detail: str | None, settings: Settings) -> None:
    if scan_status == ScanStatus.CLEAN:
        return
    if scan_status == ScanStatus.INFECTED:
        raise HTTPException(status_code=422, detail="Malware detected; upload rejected")
    # The scanner could not vet this file (UNAVAILABLE/ERROR). Fail closed by default:
    # accept an un-scanned upload ONLY when an operator has explicitly opted in via
    # RESUME_SCAN_POLICY=allow_unavailable AND app_env names a recognized development
    # context. Operators must opt IN to this lax behaviour: anything else -- a
    # forgotten or misspelled APP_ENV (e.g. "prod"), an unknown environment, or an
    # unset/unknown policy -- rejects rather than silently accepting unscanned files on
    # the unauthenticated public upload routes, so a production deploy can never fall
    # open by omission.
    dev_env = settings.app_env.lower() in {"development", "test", "local"}
    if settings.resume_scan_policy == "allow_unavailable" and dev_env:
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Malware scan unavailable; upload rejected ({detail or scan_status})",
    )


async def prepare_resume_upload(
    upload: UploadFile,
    provider: StorageProvider | None = None,
    scanner: FileScanner | None = None,
    settings: Settings | None = None,
) -> PreparedResumeUpload:
    settings = settings or get_settings()
    provider = provider or get_storage_provider(settings)
    scanner = scanner or get_file_scanner(settings)
    original_name = Path(upload.filename or "").name
    suffix = Path(original_name).suffix.lower()
    mime = (upload.content_type or "").lower()
    if not original_name or suffix not in ALLOWED_RESUMES or mime not in ALLOWED_RESUMES[suffix]:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, DOC, and DOCX resumes are accepted",
        )

    quarantine_root = Path(settings.resume_quarantine_path).resolve()
    quarantine_root.mkdir(parents=True, exist_ok=True)
    quarantine_path = (quarantine_root / f"{uuid4().hex}{suffix}").resolve()
    if quarantine_root not in quarantine_path.parents:
        raise HTTPException(status_code=400, detail="Invalid quarantine path")
    digest = hashlib.sha256()
    size = 0
    try:
        with quarantine_path.open("xb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > settings.resume_max_bytes:
                    raise HTTPException(status_code=413, detail="Resume exceeds size limit")
                digest.update(chunk)
                output.write(chunk)
        if size == 0:
            raise HTTPException(status_code=415, detail="Resume is empty")
        validate_file_signature(quarantine_path, suffix)
        scan = scanner.scan(quarantine_path)
        enforce_scan_policy(scan.status, scan.detail, settings)
        key = validate_storage_key(f"resumes/{uuid4().hex}{suffix}")
        return PreparedResumeUpload(
            ResumeUploadData(
                storage_key=key,
                original_filename=original_name,
                file_hash=digest.hexdigest(),
                file_size=size,
                mime=mime,
            ),
            quarantine_path,
            provider,
        )
    except Exception:
        quarantine_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
