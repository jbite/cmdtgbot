#!/bin/bash
# entrypoint.sh

# 確保腳本在任何命令失敗時立即退出
set -e

echo "Starting Telegram Bot..."

# 構建傳遞給 Python 腳本的參數。
# 我們從環境變數中讀取這些值，這些變數將由 docker-compose.yml 設定。
# 這樣做的好處是，這些敏感資訊不會硬編碼在 Dockerfile 或腳本中，
# 而是透過 Docker 的安全機制在運行時注入。

# 檢查所有必要的環境變數是否已設置
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
  echo "Error: TELEGRAM_BOT_TOKEN is not set."
  exit 1
fi
if [ -z "$REMOTE_SERVER_USER" ]; then
  echo "Error: REMOTE_SERVER_USER is not set."
  exit 1
fi
if [ -z "$VIDEO_PUSH_SERVER_IP_A" ]; then
  echo "Error: VIDEO_PUSH_SERVER_IP_A is not set."
  exit 1
fi
if [ -z "$VIDEO_PUSH_SERVER_IP_B" ]; then
  echo "Error: VIDEO_PUSH_SERVER_IP_B is not set."
  exit 1
fi
if [ -z "$VIDEO_FILE_SERVER_IP" ]; then
  echo "Error: VIDEO_FILE_SERVER_IP is not set."
  exit 1
fi
if [ -z "$VIDEO_PUSH_SERVER_IP_PASSWORD" ]; then
  echo "Error: VIDEO_PUSH_SERVER_IP_PASSWORD is not set."
  exit 1
fi
if [ -z "$AUTHORIZED_USER_IDS" ]; then
  echo "Error: AUTHORIZED_USER_IDS is not set. Please provide comma-separated IDs."
  exit 1
fi

# 執行 Python 腳本，並將環境變數作為命令行參數傳遞。
# "$@" 是一個特殊的 Bash 變數，它會展開為所有傳遞給腳本的命令行參數。
# 這樣做的靈活性在於，如果你未來想增加或修改 `cmdtgbot.py` 的參數，
# 只需要修改 `docker-compose.yml` 的 `command` 或 `environment` 部分，而不需要修改 `entrypoint.sh`。
exec python cmdtgbot.py \
  --token "$TELEGRAM_BOT_TOKEN" \
  --user "$REMOTE_SERVER_USER" \
  --VIDEO_PUSH_SERVER_IP_A "$VIDEO_PUSH_SERVER_IP_A" \
  --VIDEO_PUSH_SERVER_IP_B "$VIDEO_PUSH_SERVER_IP_B" \
  --VIDEO_FILE_SERVER_IP "$VIDEO_FILE_SERVER_IP" \
  --password "$VIDEO_PUSH_SERVER_IP_PASSWORD" \
  --auth_id "$AUTHORIZED_USER_IDS" \
  "$@" # 傳遞任何額外的命令列參數給 Python 腳本