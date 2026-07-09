#!/bin/bash
# Polls the `update_requested` flag set by the "Обновить панель" button on the
# web Settings page, and runs deploy.sh when it's set. Meant to be triggered
# periodically by cron or a systemd timer ON THE HOST — deliberately outside
# any container, so the web app itself never needs Docker/host access (no
# docker.sock mount, no SSH key inside the container). The app can only ever
# ask for an update; this script is what's actually allowed to perform one.
#
# One-time setup — pick one:
#
#   cron (crontab -e):
#     * * * * * cd /path/to/repo && ./scripts/update_watcher.sh >> update_watcher.log 2>&1
#
#   systemd timer (/etc/systemd/system/newsbot-update.service):
#     [Service]
#     Type=oneshot
#     WorkingDirectory=/path/to/repo
#     ExecStart=/path/to/repo/scripts/update_watcher.sh
#   (/etc/systemd/system/newsbot-update.timer):
#     [Timer]
#     OnBootSec=1min
#     OnUnitActiveSec=1min
#     [Install]
#     WantedBy=timers.target
#   Then: systemctl enable --now newsbot-update.timer
#
# Usage (on the server, from the repo root): ./scripts/update_watcher.sh
set -uo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

DB_USER="${POSTGRES_USER:-newsbot}"
DB_NAME="${POSTGRES_DB:-newsbot}"

REQUESTED_AT=$(docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -tAc \
    "SELECT value->>'requested_at' FROM settings WHERE key = 'update_requested'" 2>/dev/null)
REQUESTED_AT="$(echo "$REQUESTED_AT" | tr -d '[:space:]')"

if [ -z "$REQUESTED_AT" ]; then
    exit 0
fi

echo "==> [$(date -u +%FT%TZ)] Обновление запрошено в $REQUESTED_AT, запускаю deploy.sh"

if ./scripts/deploy.sh; then
    echo "==> [$(date -u +%FT%TZ)] Обновление завершено успешно"
else
    echo "==> [$(date -u +%FT%TZ)] deploy.sh завершился с ошибкой — флаг всё равно снимаю, чтобы не зациклиться; смотри вывод выше"
fi

docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
    "DELETE FROM settings WHERE key = 'update_requested'" >/dev/null
