import logging
import os
import argparse
import paramiko
import shlex
import datetime
import time
import re
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- State Management ---
# Using a dictionary to manage user-specific states for multi-step conversations
USER_STATE = {}
STATE_INITIAL = 0
STATE_CHOOSE_PUSH_TYPE = 1
STATE_CHOOSE_TABLE = 2

# --- Configuration (loaded from environment variables or command-line arguments) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REMOTE_SERVER_USER = os.getenv("REMOTE_SERVER_USER")
VIDEO_PUSH_SERVER_IP_A = os.getenv("VIDEO_PUSH_SERVER_IP_A")
VIDEO_PUSH_SERVER_IP_B = os.getenv("VIDEO_PUSH_SERVER_IP_B")
VIDEO_FILE_SERVER_IP = os.getenv("VIDEO_FILE_SERVER_IP") # Not explicitly used in the provided flow but good to keep
VIDEO_PUSH_SERVER_IP_PASSWORD = os.getenv("VIDEO_PUSH_SERVER_IP_PASSWORD")
AUTHORIZED_USER_IDS = [] # Will be populated from env var and parsed

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and prompts for the initial action."""
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USER_IDS:
        await update.message.reply_text("抱歉，您無權使用此機器人。")
        logger.warning(f"Unauthorized access attempt by user ID: {user_id}")
        return

    USER_STATE[user_id] = STATE_INITIAL
    keyboard = [
        [InlineKeyboardButton("重推", callback_data="重推")],
        [InlineKeyboardButton("視頻下載", callback_data="視頻下載")], # Placeholder for future functionality
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("請問要執行什麼工作？", reply_markup=reply_markup)
    logger.info(f"User {user_id} started interaction. State: INITIAL")

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles callback queries from inline keyboard buttons."""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer() # Acknowledge the callback query

    if user_id not in AUTHORIZED_USER_IDS:
        await query.edit_message_text("抱歉，您無權使用此機器人。")
        logger.warning(f"Unauthorized callback query from user ID: {user_id}")
        return

    current_state = USER_STATE.get(user_id, STATE_INITIAL)
    data = query.data

    logger.info(f"User {user_id} in state {current_state}, received callback data: {data}")

    if data == "取消":
        USER_STATE[user_id] = STATE_INITIAL
        await query.edit_message_text("操作已取消，回到初始狀態。")
        await start(update, context) # Re-prompt initial state
        return

    if current_state == STATE_INITIAL:
        if data == "重推":
            USER_STATE[user_id] = STATE_CHOOSE_PUSH_TYPE
            keyboard = [
                [InlineKeyboardButton("重推遊戲網視頻", callback_data="repush_game_net")],
                [InlineKeyboardButton("重推飛投視頻", callback_data="repush_feitou")],
                [InlineKeyboardButton("取消", callback_data="取消")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("請問我要重推遊戲網視頻還是飛投視頻？", reply_markup=reply_markup)
            logger.info(f"User {user_id} chose '重推'. State: CHOOSE_PUSH_TYPE")
        elif data == "視頻下載":
            # Placeholder for future "視頻下載" functionality
            await query.edit_message_text("視頻下載功能尚未實作，請選擇其他選項或取消。")
            await start(update, context)
            logger.info(f"User {user_id} chose '視頻下載'. Function not implemented.")
    elif current_state == STATE_CHOOSE_PUSH_TYPE:
        context.user_data['push_target'] = data # Store the chosen target (e.g., 'repush_game_net')
        USER_STATE[user_id] = STATE_CHOOSE_TABLE
        keyboard = [
            [InlineKeyboardButton(str(i), callback_data=f"table_{i}") for i in range(1, 5)],
            [InlineKeyboardButton("取消", callback_data="取消")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("請問要重推哪一桌 (1-4)?", reply_markup=reply_markup)
        logger.info(f"User {user_id} chose push target: {data}. State: CHOOSE_TABLE")
    elif current_state == STATE_CHOOSE_TABLE:
        table_number_match = re.match(r"table_(\d)", data)
        if table_number_match:
            table_number = int(table_number_match.group(1))
            context.user_data['table_number'] = table_number
            
            # Confirm with the user
            push_target_display = "遊戲網視頻" if context.user_data['push_target'] == "repush_game_net" else "飛投視頻"
            
            keyboard = [
                [InlineKeyboardButton("是", callback_data="confirm_yes")],
                [InlineKeyboardButton("否", callback_data="confirm_no")],
                [InlineKeyboardButton("取消", callback_data="取消")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"您確定要重推 {push_target_display} 的第 {table_number} 桌嗎？",
                reply_markup=reply_markup
            )
            logger.info(f"User {user_id} chose table {table_number}. Awaiting confirmation.")
        elif data == "confirm_yes":
            push_target = context.user_data.get('push_target')
            table_number = context.user_data.get('table_number')

            if push_target and table_number is not None:
                server_ip = VIDEO_PUSH_SERVER_IP_A if push_target == "repush_game_net" else VIDEO_PUSH_SERVER_IP_B
                
                # Execute the SSH command
                try:
                    client = paramiko.SSHClient()
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    client.connect(hostname=server_ip, username=REMOTE_SERVER_USER, password=VIDEO_PUSH_SERVER_IP_PASSWORD, timeout=10)
                    
                    command = f"docker restart streaming_script-ffmpeg_bk0{table_number}-1"
                    logger.info(f"Executing command on {server_ip}: {command}")
                    
                    stdin, stdout, stderr = client.exec_command(command)
                    stdout_output = stdout.read().decode().strip()
                    stderr_output = stderr.read().decode().strip()

                    if stdout_output:
                        await query.edit_message_text(f"指令執行成功:\n`{stdout_output}`", parse_mode='Markdown')
                        logger.info(f"Command success output: {stdout_output}")
                    if stderr_output:
                        await query.edit_message_text(f"指令執行警告或錯誤:\n`{stderr_output}`", parse_mode='Markdown')
                        logger.warning(f"Command stderr output: {stderr_output}")

                    if not stdout_output and not stderr_output:
                         await query.edit_message_text("指令已送出，無明確輸出。")
                         logger.info("Command sent with no output.")
                    
                except paramiko.AuthenticationException:
                    await query.edit_message_text("SSH 連線失敗：認證錯誤，請檢查帳號密碼。")
                    logger.error(f"SSH Auth Error for {REMOTE_SERVER_USER}@{server_ip}")
                except paramiko.SSHException as e:
                    await query.edit_message_text(f"SSH 連線失敗：{e}")
                    logger.error(f"SSH connection error for {REMOTE_SERVER_USER}@{server_ip}: {e}")
                except Exception as e:
                    await query.edit_message_text(f"執行指令時發生錯誤：{e}")
                    logger.error(f"Error executing command: {e}")
                finally:
                    if 'client' in locals() and client:
                        client.close()
                
                # Reset state after execution
                USER_STATE[user_id] = STATE_INITIAL
                await asyncio.sleep(1) # Give time for the previous message to render
                await start(update, context) # Go back to initial prompt
                logger.info(f"User {user_id} confirmed and command executed. State reset to INITIAL.")

            else:
                await query.edit_message_text("發生錯誤，請重新開始。")
                USER_STATE[user_id] = STATE_INITIAL
                await start(update, context)
                logger.error(f"User {user_id} confirmation failed: missing push_target or table_number in user_data.")
        elif data == "confirm_no":
            await query.edit_message_text("您已取消重推操作。")
            USER_STATE[user_id] = STATE_INITIAL
            await start(update, context)
            logger.info(f"User {user_id} declined confirmation. State reset to INITIAL.")
        else:
            await query.edit_message_text("無效的選擇，請重新開始。")
            USER_STATE[user_id] = STATE_INITIAL
            await start(update, context)
            logger.warning(f"User {user_id} made invalid selection in STATE_CHOOSE_TABLE. Data: {data}")

async def fallback_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages that don't match any specific command or callback."""
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USER_IDS:
        logger.warning(f"Unauthorized message from user ID: {user_id} - '{update.message.text}'")
        return

    # If the user sends a text message not matching any specific handler,
    # just reset their state and prompt them again.
    USER_STATE[user_id] = STATE_INITIAL
    await update.message.reply_text("無法理解您的指令，請使用提供的選項。")
    await start(update, context)
    logger.info(f"User {user_id} sent unhandled message: '{update.message.text}'. State reset to INITIAL.")


def main() -> None:
    """Starts the bot."""
    # Parse command-line arguments if provided, otherwise rely on environment variables
    parser = argparse.ArgumentParser(description="Telegram Bot for server operations.")
    parser.add_argument("--token", help="Telegram Bot Token")
    parser.add_argument("--user", help="Remote Server User")
    parser.add_argument("--VIDEO_PUSH_SERVER_IP_A", help="IP for Video Push Server A")
    parser.add_argument("--VIDEO_PUSH_SERVER_IP_B", help="IP for Video Push Server B")
    parser.add_argument("--VIDEO_FILE_SERVER_IP", help="IP for Video File Server")
    parser.add_argument("--password", help="Password for Video Push Servers")
    parser.add_argument("--auth_id", help="Comma-separated authorized Telegram User IDs")

    args = parser.parse_args()

    # Prefer command line arguments, then environment variables
    global TELEGRAM_BOT_TOKEN, REMOTE_SERVER_USER, VIDEO_PUSH_SERVER_IP_A, \
           VIDEO_PUSH_SERVER_IP_B, VIDEO_FILE_SERVER_IP, VIDEO_PUSH_SERVER_IP_PASSWORD, \
           AUTHORIZED_USER_IDS

    TELEGRAM_BOT_TOKEN = args.token or TELEGRAM_BOT_TOKEN
    REMOTE_SERVER_USER = args.user or REMOTE_SERVER_USER
    VIDEO_PUSH_SERVER_IP_A = args.VIDEO_PUSH_SERVER_IP_A or VIDEO_PUSH_SERVER_IP_A
    VIDEO_PUSH_SERVER_IP_B = args.VIDEO_PUSH_SERVER_IP_B or VIDEO_PUSH_SERVER_IP_B
    VIDEO_FILE_SERVER_IP = args.VIDEO_FILE_SERVER_IP or VIDEO_FILE_SERVER_IP
    VIDEO_PUSH_SERVER_IP_PASSWORD = args.password or VIDEO_PUSH_SERVER_IP_PASSWORD
    
    if args.auth_id:
        AUTHORIZED_USER_IDS = [int(uid.strip()) for uid in args.auth_id.split(',') if uid.strip().isdigit()]
    elif os.getenv("AUTHORIZED_USER_IDS"):
        AUTHORIZED_USER_IDS = [int(uid.strip()) for uid in os.getenv("AUTHORIZED_USER_IDS").split(',') if uid.strip().isdigit()]

    if not all([TELEGRAM_BOT_TOKEN, REMOTE_SERVER_USER, VIDEO_PUSH_SERVER_IP_A,
                VIDEO_PUSH_SERVER_IP_B, VIDEO_PUSH_SERVER_IP_PASSWORD, AUTHORIZED_USER_IDS]):
        logger.error("Missing one or more required configuration parameters. Please check environment variables or command-line arguments.")
        exit(1)

    logger.info(f"Bot starting with authorized users: {AUTHORIZED_USER_IDS}")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))

    # Callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Message handler to catch any other messages and guide the user
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_message))


    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()