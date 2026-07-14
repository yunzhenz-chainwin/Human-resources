import shutil
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.dependencies.auth import audit_pii_read, get_current_user
from app.main import app


def _png(width: int = 80, height: int = 80) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    scanlines = b"".join(b"\x00" + (b"\x39\x8d\x7a" * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


@pytest.fixture()
def photo_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    storage = Path("storage") / f"candidate-photo-test-{uuid4().hex}"
    original_storage = get_settings().candidate_photo_storage_path
    get_settings().candidate_photo_storage_path = str(storage)

    def override_db():
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, role="admin", department_id=None, is_active=True
    )
    app.dependency_overrides[audit_pii_read] = lambda: None
    with TestClient(app) as client:
        yield client, storage
    app.dependency_overrides.clear()
    get_settings().candidate_photo_storage_path = original_storage
    Base.metadata.drop_all(engine)
    shutil.rmtree(storage, ignore_errors=True)


def test_candidate_photo_upload_read_replace_and_delete(photo_client) -> None:
    client, storage = photo_client
    candidate = client.post("/api/v1/candidates", json={"name": "Photo Candidate"}).json()
    assert candidate["has_photo"] is False

    uploaded = client.put(
        f"/api/v1/candidates/{candidate['id']}/photo",
        files={"photo": ("../../avatar.png", _png(), "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["has_photo"] is True
    saved_files = list(storage.glob("*"))
    assert len(saved_files) == 1
    assert ".." not in saved_files[0].name

    downloaded = client.get(f"/api/v1/candidates/{candidate['id']}/photo")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "image/png"
    assert downloaded.content == _png()

    removed = client.delete(f"/api/v1/candidates/{candidate['id']}/photo")
    assert removed.status_code == 204
    assert not list(storage.glob("*"))
    assert client.get(f"/api/v1/candidates/{candidate['id']}/photo").status_code == 404


def test_candidate_photo_rejects_spoofed_and_oversized_files(photo_client) -> None:
    client, _storage = photo_client
    candidate_id = client.post(
        "/api/v1/candidates", json={"name": "Invalid Photo"}
    ).json()["id"]
    spoofed = client.put(
        f"/api/v1/candidates/{candidate_id}/photo",
        files={"photo": ("avatar.png", b"not really an image", "image/png")},
    )
    assert spoofed.status_code == 415

    oversized = client.put(
        f"/api/v1/candidates/{candidate_id}/photo",
        files={"photo": ("avatar.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
    )
    assert oversized.status_code == 413
