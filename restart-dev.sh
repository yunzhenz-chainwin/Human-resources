#!/usr/bin/env bash
# Safely stop and restart the TalentHub local development environment.
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$root/stop-dev.sh"
sleep 1
"$root/start-dev.sh"
