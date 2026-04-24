#!/usr/bin/env bash
# Install/remove a daily crontab entry for the newsletter.
#
# Usage:
#   ./scripts/schedule_cron.sh install           # daily at 07:00
#   ./scripts/schedule_cron.sh install 09 30     # daily at 09:30
#   ./scripts/schedule_cron.sh install-email     # daily at 07:00 with --email
#   ./scripts/schedule_cron.sh remove
#
# Writes output to ./output/cron.log so you can verify it's running.

set -euo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd -- "$here/.." && pwd)"
marker="# newsletter-ai:$root"
python_bin="${PYTHON:-$(command -v python3 || command -v python)}"

if [[ -z "${python_bin}" ]]; then
    echo "python not found on PATH; set PYTHON=/path/to/python and retry" >&2
    exit 1
fi

log_file="$root/output/cron.log"

current_crontab() {
    crontab -l 2>/dev/null || true
}

strip_existing() {
    current_crontab | grep -vF "$marker" || true
}

case "${1:-}" in
    install|install-email)
        hour="${2:-07}"
        minute="${3:-00}"
        flags=""
        if [[ "$1" == "install-email" ]]; then
            flags=" --email"
        fi
        line="$minute $hour * * * cd \"$root\" && \"$python_bin\" main.py$flags >> \"$log_file\" 2>&1 $marker"
        { strip_existing; echo "$line"; } | crontab -
        echo "Installed cron entry:"
        echo "  $line"
        ;;
    remove)
        strip_existing | crontab -
        echo "Removed any cron entries tagged $marker"
        ;;
    *)
        echo "Usage: $0 install [HH] [MM] | install-email [HH] [MM] | remove" >&2
        exit 1
        ;;
esac
