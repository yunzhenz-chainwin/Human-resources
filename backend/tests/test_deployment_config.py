from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_compose_persists_resume_and_candidate_photo_storage() -> None:
    compose = text("deploy/docker-compose.yml")
    assert "resume_data:/app/storage/resumes" in compose
    assert "candidate_photo_data:/app/storage/candidate-photos" in compose
    assert "  candidate_photo_data:" in compose


def test_docker_build_contexts_exclude_local_secrets_and_runtime_data() -> None:
    required = {".env", ".env.*", "node_modules", "dist", "*.log"}
    for project in ("frontend", "career-frontend"):
        patterns = set(text(f"{project}/.dockerignore").splitlines())
        assert required <= patterns

    backend_patterns = set(text("backend/.dockerignore").splitlines())
    assert {".env", ".env.*", "*.db", "storage", "*.log", "tests"} <= backend_patterns


def test_hr_container_accepts_supported_upload_size_and_uses_lockfile() -> None:
    for project in ("frontend", "career-frontend"):
        nginx = text(f"{project}/nginx.conf")
        assert "client_max_body_size 11m;" in nginx
        assert "proxy_request_buffering off;" in nginx
        assert "proxy_read_timeout 120s;" in nginx
        assert "proxy_send_timeout 120s;" in nginx
    dockerfile = text("frontend/Dockerfile")
    assert "RUN npm ci" in dockerfile
    assert "RUN npm install" not in dockerfile
