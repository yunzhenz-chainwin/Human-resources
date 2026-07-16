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


def test_vite_lan_access_uses_fixed_ports_and_explicit_host_allowlist() -> None:
    expected_ports = {"frontend/vite.config.js": "5173", "career-frontend/vite.config.js": "5174"}
    for path, port in expected_ports.items():
        config = text(path)
        assert "host: '0.0.0.0'" in config
        assert f"port: {port}" in config
        assert "strictPort: true" in config
        assert "machineHostname.toLowerCase()" in config
        assert "VITE_ALLOWED_HOSTS" in config
        assert "target: proxyTarget" in config


def test_windows_lan_firewall_keeps_backend_private() -> None:
    firewall = text("deploy/windows-lan/install-firewall.ps1")
    assert "-LocalPort 5173,5174" in firewall
    assert "LocalSubnet" in firewall
    assert "8010" not in firewall

    runner = text("deploy/windows-lan/run-service.ps1")
    assert "alembic upgrade head" in runner
    assert "run_backend.py" in runner
