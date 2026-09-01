#!/usr/bin/env bash
# TalentHub local development launcher for macOS and Linux.
# The Windows twin is start-dev.ps1; keep the two in step when ports or health
# checks change. Repeated runs skip healthy services instead of producing port
# conflicts.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log_dir="$root/.dev-logs"
mkdir -p "$log_dir"

# Prefer the repo venv created by setup-mac.sh so the launcher does not depend on
# whichever interpreter happens to be first on PATH.
if [[ -x "$root/.venv/bin/python" ]]; then
    python_bin="$root/.venv/bin/python"
else
    python_bin="$(command -v python3 || command -v python)"
fi

http_ok() { # url [expected_text]
    local url="$1" expected="${2-}" body
    body="$(curl -fsS --max-time 2 "$url" 2>/dev/null)" || return 1
    [[ -z "$expected" || "$body" == *"$expected"* ]]
}

listening_pid() {
    lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null | head -1
}

start_service() { # name port health_url expected workdir command...
    local name="$1" port="$2" health_url="$3" expected="$4" workdir="$5"
    shift 5

    if http_ok "$health_url" "$expected"; then
        printf '[OK] %s is already healthy on port %s. Skipping duplicate start.\n' "$name" "$port"
        return
    fi

    local held
    held="$(listening_pid "$port")"
    if [[ -n "$held" ]]; then
        printf '[WARN] Port %s for %s is held by PID %s, but its health check failed.\n' "$port" "$name" "$held"
        printf '       Run ./restart-dev.sh, or run ./stop-dev.sh before starting again.\n'
        return
    fi

    local log="$log_dir/${port}.log"
    ( cd "$workdir" && exec "$@" ) >"$log" 2>&1 &
    printf '[START] Starting %s... (log: %s)\n' "$name" "${log#"$root/"}"
}

printf 'TalentHub development environment check\n'

start_service "TalentHub Backend API" 8010 \
    "http://127.0.0.1:8010/api/v1/health" "talenthub-api" \
    "$root/backend" "$python_bin" run_backend.py

start_service "TalentHub HR Admin" 5173 \
    "http://127.0.0.1:5173/src/main.ts" "" \
    "$root/frontend" npm run dev

start_service "TalentHub Career Site" 5174 \
    "http://127.0.0.1:5174/src/main.ts" "" \
    "$root/career-frontend" npm run dev

for _ in $(seq 1 15); do
    if http_ok "http://127.0.0.1:8010/api/v1/health" "talenthub-api" \
        && http_ok "http://127.0.0.1:5173/src/main.ts" \
        && http_ok "http://127.0.0.1:5174/src/main.ts"; then
        break
    fi
    sleep 1
done

printf '\nService status:\n'
check() { # label probe expected url
    local label="$1" probe="$2" expected="$3" url="$4"
    if http_ok "$probe" "$expected"; then
        printf '  %-12s %-10s %s\n' "$label" "READY" "$url"
    else
        printf '  %-12s %-10s %s\n' "$label" "NOT READY" "$url"
    fi
}
check "HR Admin"    "http://127.0.0.1:5173/src/main.ts"   ""              "http://127.0.0.1:5173/"
check "Career Site" "http://127.0.0.1:5174/src/main.ts"   ""              "http://127.0.0.1:5174/"
check "Backend API" "http://127.0.0.1:8010/api/v1/health" "talenthub-api" "http://127.0.0.1:8010/api/v1/health"

printf '\nUse ./restart-dev.sh for a clean restart.\n'
printf 'Use ./stop-dev.sh to stop the three verified TalentHub services.\n'

lan_address="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
if [[ -n "$lan_address" ]]; then
    printf '\nLAN URLs (vite must be started with --host to accept them):\n'
    printf '  HR / manager: http://%s:5173/\n' "$lan_address"
    printf '  Career site:  http://%s:5174/\n' "$lan_address"
    printf 'Do not expose these HTTP development ports directly to the public Internet.\n'
fi
