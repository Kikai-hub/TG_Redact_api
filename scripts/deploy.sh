#!/bin/bash
# Deploy the latest committed version on THIS server: fetch, fast-forward
# pull, rebuild only what changed, restart containers. Safe to run anytime —
# it's a no-op if there's nothing new, and refuses to touch anything if the
# working tree has uncommitted local changes.
#
# Usage (on the server, from anywhere): ./scripts/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain)" ]; then
    echo "⚠ В рабочей директории есть незакоммиченные изменения — прерываю, чтобы ничего не потерять."
    git status --short
    exit 1
fi

echo "==> Текущий коммит: $(git rev-parse --short HEAD)"
echo "==> Проверяю обновления..."
git fetch --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse '@{u}')

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "==> Обновлений нет, всё уже актуально."
    exit 0
fi

PREV_COMMIT=$(git rev-parse --short HEAD)
echo "==> Есть обновления, подтягиваю (fast-forward)..."
git merge --ff-only '@{u}'

if [ -f .env.example ] && [ -f .env ]; then
    MISSING=$(comm -23 <(grep -oE '^[A-Z_]+' .env.example | sort -u) <(grep -oE '^[A-Z_]+' .env | sort -u) || true)
    if [ -n "$MISSING" ]; then
        echo "⚠ В .env отсутствуют переменные, которые есть в .env.example (проверьте, нужно ли их задать):"
        echo "$MISSING" | sed 's/^/   /'
    fi
fi

echo "==> Пересобираю и перезапускаю контейнеры..."
docker compose up -d --build --remove-orphans

echo
echo "==> Готово: $PREV_COMMIT -> $(git rev-parse --short HEAD)"
docker compose ps
echo
echo "Если что-то сломалось — откат:"
echo "  git reset --hard $PREV_COMMIT && docker compose up -d --build"
