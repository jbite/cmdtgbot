#!/bin/bash
# This script will execute the main Python application, passing along
# environment variables as command-line arguments to cmdtgbot.py.

# Make sure all required environment variables are set.
# You can add checks here if you want to fail early for missing variables.

echo "Starting Telegram bot..."
echo "REMOTE_SERVER_USER: $REMOTE_SERVER_USER"
echo "VIDEO_PUSH_SERVER_IP_A: $VIDEO_PUSH_SERVER_IP_A"
echo "VIDEO_PUSH_SERVER_IP_B: $VIDEO_PUSH_SERVER_IP_B"
echo "VIDEO_FILE_SERVER_IP: $VIDEO_FILE_SERVER_IP"
# WARNING: Do not echo TELEGRAM_BOT_TOKEN or VIDEO_PUSH_SERVER_IP_PASSWORD in production logs!
# echo "TELEGRAM_BOT_TOKEN: $TELEGRAM_BOT_TOKEN"
# echo "VIDEO_PUSH_SERVER_IP_PASSWORD: $VIDEO_PUSH_SERVER_IP_PASSWORD"
echo "AUTHORIZED_USER_IDS: $AUTHORIZED_USER_IDS"

# Execute the Python script, passing environment variables as arguments.
# This makes it easier to test the script directly or integrate with other systems
# that prefer command-line arguments over env vars for specific configs.
python cmdtgbot.py \
  --token "$TELEGRAM_BOT_TOKEN" \
  --user "$REMOTE_SERVER_USER" \
  --VIDEO_PUSH_SERVER_IP_A "$VIDEO_PUSH_SERVER_IP_A" \
  --VIDEO_PUSH_SERVER_IP_B "$VIDEO_PUSH_SERVER_IP_B" \
  --VIDEO_FILE_SERVER_IP "$VIDEO_FILE_SERVER_IP" \
  --password "$VIDEO_PUSH_SERVER_IP_PASSWORD" \
  --auth_id "$AUTHORIZED_USER_IDS"

# The script will keep running as long as the Python application is running.