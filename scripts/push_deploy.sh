#!/bin/bash
# Run from your LOCAL machine (Git Bash) to push the current branch to the
# server and trigger a deploy there in one step. Fill in the three variables
# below once (matches the `production` remote set up during initial deploy).
#
# Usage: bash scripts/push_deploy.sh
set -euo pipefail

SERVER_USER="ваш_user"
SERVER_HOST="ваш_сервер"
SERVER_PATH="/home/ваш_user/newsbot"

echo "==> Пушу текущую ветку в production..."
git push production main

echo "==> Запускаю деплой на сервере..."
ssh "${SERVER_USER}@${SERVER_HOST}" "cd '${SERVER_PATH}' && ./scripts/deploy.sh"
