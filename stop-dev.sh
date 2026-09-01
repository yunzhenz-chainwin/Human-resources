#!/usr/bin/env bash
# Stops only listeners that can be verified as TalentHub development services.
# The Windows twin is stop-dev.ps1.
set -uo pipefail

listening_pid() {
    lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null | head -1
}

# Verify before killing: a bare port match would take down whatever unrelated
# process happens to hold 5173 on a developer's machine.
is_talenthub() { # pid expected_command health_url expected_text
    local pid="$1" expected_command="$2" health_url="$3" expected_text="$4" command_name body
    command_name="$(ps -p "$pid" -o comm= 2>/dev/null)" || return 1
    [[ "$command_name" == *"$expected_command"* ]] || return 1
    body="$(curl -fsS --max-time 2 "$health_url" 2>/dev/null)" || return 1
    [[ "$body" == *"$expected_text"* ]]
}

stop_service() { # name port expected_command health_url expected_text
    local name="$1" port="$2" expected_command="$3" health_url="$4" expected_text="$5" pid
    pid="$(listening_pid "$port")"
    if [[ -z "$pid" ]]; then
        printf '[SKIP] %s is not listening on port %s.\n' "$name" "$port"
        return
    fi
    if ! is_talenthub "$pid" "$expected_command" "$health_url" "$expected_text"; then
        printf '[SKIP] PID %s holds port %s but is not a verified %s. Left running.\n' "$pid" "$port" "$name"
        return
    fi
    # The vite and uvicorn parents both spawn children; killing the process group
    # is what actually frees the port.
    kill -TERM -- "-$(ps -o pgid= "$pid" | tr -d ' ')" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    printf '[STOP] Stopped %s (PID %s) on port %s.\n' "$name" "$pid" "$port"
}

stop_service "TalentHub Backend API" 8010 python \
    "http://127.0.0.1:8010/api/v1/health" "talenthub-api"
stop_service "TalentHub HR Admin" 5173 node \
    "http://127.0.0.1:5173/src/main.ts" "main.ts"
stop_service "TalentHub Career Site" 5174 node \
    "http://127.0.0.1:5174/src/main.ts" "main.ts"
