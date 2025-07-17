import logging
import os
import argparse
import paramiko
import shlex
import datetime
import time
import re
import asyncio
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables (will be loaded from docker-compose)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REMOTE_SERVER_USER = os.getenv("REMOTE_SERVER_USER")
VIDEO_PUSH_SERVER_IP_A = os.getenv("VIDEO_PUSH_SERVER_IP_A")
VIDEO_PUSH_SERVER_IP_B = os.getenv("VIDEO_PUSH_SERVER_IP_B")
VIDEO_FILE_SERVER_IP = os.getenv("VIDEO_FILE_SERVER_IP") # Not used in current flow, but kept for completeness
VIDEO_PUSH_SERVER_IP_PASSWORD = os.getenv("VIDEO_PUSH_SERVER_IP_PASSWORD")
AUTHORIZED_USER_IDS_STR = os.getenv("AUTHORIZED_USER_IDS")
AUTHORIZED_USER_IDS = [int(uid.strip()) for uid in AUTHORIZED_USER_IDS_STR.split(',')] if AUTHORIZED_USER_IDS_STR else []

# State management for the conversation flow
USER_STATE = {} # {user_id: {"state": "current_state", "data": {}}}

# Constants for states
STATE_INITIAL = "initial"
STATE_SELECT_SERVER = "select_server"
STATE_SELECT_TABLE = "select_table"
STATE_CONFIRM_RESTART = "confirm_restart"

async def authorize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if the user is authorized to use the bot."""
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USER_IDS:
        await update.message.reply_text(
            "抱歉，您無權使用此機器人。請聯繫管理員。",
            reply_markup=ReplyKeyboardRemove()
        )
        logger.warning(f"Unauthorized access attempt by user ID: {user_id}")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message with options to start a new task."""
    if not await authorize(update, context):
        return

    user_id = update.effective_user.id
    USER_STATE[user_id] = {"state": STATE_INITIAL}

    keyboard = [["重推"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("請問要執行什麼工作？", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming messages based on current user state."""
    if not await authorize(update, context):
        return

    user_id = update.effective_user.id
    user_message = update.message.text
    current_state = USER_STATE.get(user_id, {}).get("state", STATE_INITIAL)

    logger.info(f"User {user_id} in state {current_state} sent message: {user_message}")

    if user_message == "取消":
        await start(update, context) # Go back to initial state
        return

    if current_state == STATE_INITIAL:
        if user_message == "重推":
            USER_STATE[user_id]["state"] = STATE_SELECT_SERVER
            keyboard = [["遊戲網視頻 (A)", "飛投視頻 (B)"], ["取消"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            await update.message.reply_text(
                "請問要重推遊戲網視頻(VIDEO_PUSH_SERVER_IP_A)還是飛投視頻(VIDEO_PUSH_SERVER_IP_B)?",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text("無效的選項，請選擇 '重推' 或 '取消'。", reply_markup=ReplyKeyboardRemove())
            await start(update, context)

    elif current_state == STATE_SELECT_SERVER:
        selected_server = None
        if user_message == "遊戲網視頻 (A)":
            selected_server = "A"
        elif user_message == "飛投視頻 (B)":
            selected_server = "B"
        else:
            await update.message.reply_text("無效的選擇，請選擇 '遊戲網視頻 (A)' 或 '飛投視頻 (B)' 或 '取消'。", reply_markup=ReplyKeyboardRemove())
            await start(update, context)
            return

        if selected_server:
            USER_STATE[user_id]["state"] = STATE_SELECT_TABLE
            USER_STATE[user_id]["data"] = {"server": selected_server}
            keyboard = [
                ["1", "2", "3", "4"],
                ["取消"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            await update.message.reply_text("請問要重推哪一桌 (1-4)?", reply_markup=reply_markup)

    elif current_state == STATE_SELECT_TABLE:
        try:
            table_number = int(user_message)
            if 1 <= table_number <= 4:
                USER_STATE[user_id]["data"]["table"] = table_number
                USER_STATE[user_id]["state"] = STATE_CONFIRM_RESTART
                server_name = "遊戲網視頻" if USER_STATE[user_id]["data"]["server"] == "A" else "飛投視頻"
                keyboard = [["是", "否"], ["取消"]]
                reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
                await update.message.reply_text(
                    f"您是否確認要重推 {server_name} 的第 {table_number} 桌?",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text("無效的桌號，請輸入 1-4 之間的數字或 '取消'。", reply_markup=ReplyKeyboardRemove())
                # Stay in SELECT_TABLE state, or go back to start if preferred
                await start(update, context) # Going back to start for simplicity on invalid input
        except ValueError:
            await update.message.reply_text("無效的輸入，請輸入數字 (1-4) 或 '取消'。", reply_markup=ReplyKeyboardRemove())
            await start(update, context) # Going back to start for simplicity on invalid input

    elif current_state == STATE_CONFIRM_RESTART:
        if user_message == "是":
            server_type = USER_STATE[user_id]["data"]["server"]
            table_number = USER_STATE[user_id]["data"]["table"]

            server_ip = VIDEO_PUSH_SERVER_IP_A if server_type == "A" else VIDEO_PUSH_SERVER_IP_B
            container_name = f"streaming_script-ffmpeg_bk0{table_number}-1"

            try:
                await update.message.reply_text(f"正在重啟 {container_name} 在 {server_ip}...", reply_markup=ReplyKeyboardRemove())
                output = await execute_remote_command(
                    server_ip,
                    REMOTE_SERVER_USER,
                    VIDEO_PUSH_SERVER_IP_PASSWORD,
                    f"docker restart {container_name}"
                )
                await update.message.reply_text(f"重啟指令執行完成，結果:\n```{output}```", parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Error executing remote command: {e}")
                await update.message.reply_text(f"執行遠端指令時發生錯誤: {e}", reply_markup=ReplyKeyboardRemove())
            finally:
                await start(update, context) # Reset after command execution
        elif user_message == "否":
            await update.message.reply_text("已取消操作。", reply_markup=ReplyKeyboardRemove())
            await start(update, context) # Go back to initial state
        else:
            await update.message.reply_text("無效的選擇，請選擇 '是' 或 '否' 或 '取消'。", reply_markup=ReplyKeyboardRemove())
            await start(update, context)

async def execute_remote_command(hostname, username, password, command) -> str:
    """Executes a command on a remote server via SSH."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(hostname=hostname, username=username, password=password, timeout=10)
        logger.info(f"Connected to {hostname} as {username}")
        stdin, stdout, stderr = client.exec_command(command)
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()
        if error:
            logger.error(f"Remote command error on {hostname}: {error}")
            raise Exception(f"SSH Error: {error}")
        return output
    finally:
        client.close()

def main() -> None:
    """Start the bot."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()