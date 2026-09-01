#!/usr/bin/env bash
# One-shot bootstrap for a fresh macOS checkout of TalentHub.
# Safe to re-run: every step is idempotent and skips work already done.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"
failed=0

step() { printf '\n=== %s ===\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failed=1; }

step "Checking prerequisites"

# The backend pins >=3.12; the macOS system python3 is older than that on most
# machines, so look for a real 3.12+ before creating the venv.
python_bin=""
for candidate in python3.13 python3.12 python3; do
    path="$(command -v "$candidate" 2>/dev/null)" || continue
    if "$path" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
        python_bin="$path"
        break
    fi
done
if [[ -z "$python_bin" ]]; then
    fail "Python 3.12+ not found. Install it with:  brew install python@3.12"
else
    printf '[OK] Python: %s (%s)\n' "$python_bin" "$("$python_bin" --version)"
fi

if command -v node >/dev/null 2>&1; then
    printf '[OK] Node: %s\n' "$(node --version)"
else
    fail "Node.js not found. Install it with:  brew install node"
fi

# OCR is only needed for scanned PDFs; a missing toolchain degrades resume
# parsing rather than breaking startup, so these are warnings, not failures.
command -v tesseract >/dev/null 2>&1 \
    && printf '[OK] tesseract: %s\n' "$(command -v tesseract)" \
    || warn "tesseract not found — scanned-PDF OCR will be unavailable.  brew install tesseract tesseract-lang"
command -v pdftoppm >/dev/null 2>&1 \
    && printf '[OK] poppler: %s\n' "$(command -v pdftoppm)" \
    || warn "poppler not found — scanned-PDF OCR will be unavailable.  brew install poppler"

# fpdf renders the candidate and de-identified PDFs and needs a CJK face.
if [[ -f /System/Library/Fonts/PingFang.ttc || -f /Library/Fonts/NotoSansCJK-Regular.ttc \
      || -f "$HOME/Library/Fonts/NotoSansCJK-Regular.ttc" ]]; then
    printf '[OK] Traditional Chinese PDF font present\n'
else
    warn "No CJK PDF font found — PDF export will fail.  brew install --cask font-noto-sans-cjk"
fi

if (( failed )); then
    printf '\nInstall the missing prerequisites above, then re-run ./setup-mac.sh\n'
    exit 1
fi

step "Creating the Python virtualenv (.venv)"
[[ -d .venv ]] || "$python_bin" -m venv .venv
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -e "backend[dev]" || fail "backend dependency install failed"

step "Installing frontend dependencies"
( cd frontend && npm ci ) || fail "frontend npm ci failed"
( cd career-frontend && npm ci ) || fail "career-frontend npm ci failed"

step "Preparing backend/.env"
if [[ -f backend/.env ]]; then
    printf '[OK] backend/.env already exists — left untouched.\n'
else
    cp .env.example backend/.env
    # AUTH_SECRET_KEY has no usable default; generate one rather than leaving the
    # blank that makes the API refuse to start.
    secret="$(./.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))')"
    /usr/bin/sed -i '' \
        -e "s|^AUTH_SECRET_KEY=.*|AUTH_SECRET_KEY=${secret}|" \
        -e "s|^DATABASE_URL=.*|DATABASE_URL=sqlite:///./talenthub-preserved-accounts.db|" \
        backend/.env
    printf '[OK] Created backend/.env with a fresh AUTH_SECRET_KEY and a local SQLite URL.\n'
    printf '     Set GEMINI_API_KEY there if manager interview-question generation is needed.\n'
    printf '     Uncomment the three BOOTSTRAP_ADMIN_* lines once to create the first admin,\n'
    printf '     start the API, then remove them again.\n'
fi

step "Running database migrations"
( cd backend && "$root/.venv/bin/python" -m alembic upgrade head ) || fail "alembic upgrade failed"

if (( failed )); then
    printf '\nSetup finished with errors — see [FAIL] lines above.\n'
    exit 1
fi

printf '\nSetup complete. Start everything with:\n\n    ./start-dev.sh\n\n'
printf '  HR admin:    http://127.0.0.1:5173/\n'
printf '  Career site: http://127.0.0.1:5174/\n'
printf '  API health:  http://127.0.0.1:8010/api/v1/health\n'
