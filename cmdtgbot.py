import logging
import os
import argparse
import asyncio
import datetime
import re

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# 導入 Paramiko 模組
import paramiko

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for the conversation handler
(
    SELECT_ACTION,
    SELECT_PUSH_SERVER,
    SELECT_TABLE_FOR_PUSH,
    CONFIRM_PUSH,
    SELECT_TABLE_FOR_DOWNLOAD,
    SELECT_DOWNLOAD_TIME,
    SELECT_FILE_FOR_DOWNLOAD, # New state for file selection
    CONFIRM_DOWNLOAD,
) = range(8) # Updated range to include new state

# Global variables loaded from environment or command line arguments
TELEGRAM_BOT_TOKEN = None
REMOTE_SERVER_USER = None
VIDEO_PUSH_SERVER_IP_A = None
VIDEO_PUSH_SERVER_IP_B = None
VIDEO_FILE_SERVER_IP = None
VIDEO_PUSH_SERVER_IP_PASSWORD = None
AUTHORIZED_USER_IDS = [] # 將從命令行參數解析為列表
VIDEO_BASE_PATH = None

# --- Utility Functions ---

async def is_authorized(update: Update) -> bool:
    """Check if the user is authorized to use the bot."""
    user_id = str(update.effective_user.id)
    if user_id not in AUTHORIZED_USER_IDS:
        logger.warning(f"Unauthorized access attempt from user ID: {user_id}")
        await update.message.reply_text("抱歉，您沒有權限執行此操作。")
        return False
    return True

async def run_ssh_command(host: str, user: str, password: str, command: str) -> tuple[int, str, str]:
    """
    Executes an SSH command on a remote server using Paramiko.
    Returns (return_code, stdout, stderr).
    """
    ssh_client = paramiko.SSHClient()
    # 自動添加未知主機的 key，這在測試環境中很方便。
    # ❗️生產環境中，建議載入系統的 known_hosts 或明確指定已知主機金鑰，
    # 例如 ssh_client.load_system_host_keys() 或 ssh_client.load_host_keys('path/to/known_hosts')
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        logger.info(f"Connecting to SSH host {user}@{host}")
        ssh_client.connect(hostname=host, username=user, password=password, timeout=10) # 增加 timeout 防止無限等待
        logger.info(f"Executing command on {host}: {command}")
        
        # 執行命令
        stdin, stdout, stderr = ssh_client.exec_command(command)
        
        # 讀取輸出，等待命令完成
        stdout_str = stdout.read().decode().strip()
        stderr_str = stderr.read().decode().strip()
        
        # 獲取命令的退出狀態碼
        exit_status = stdout.channel.recv_exit_status() 
        
        logger.info(f"Command on {host} finished with exit status: {exit_status}")
        if stdout_str:
            logger.debug(f"STDOUT: {stdout_str}")
        if stderr_str:
            logger.debug(f"STDERR: {stderr_str}")

        return exit_status, stdout_str, stderr_str

    except paramiko.AuthenticationException:
        logger.error(f"Authentication failed for {user}@{host}. Please check credentials.")
        return 1, "", "認證失敗，請檢查用戶名和密碼。"
    except paramiko.SSHException as e:
        logger.error(f"SSH connection failed or command execution error on {host}: {e}")
        return 1, "", f"SSH 連線或執行命令錯誤: {e}"
    except Exception as e:
        logger.error(f"General error running SSH command on {host}: {e}")
        return 1, "", f"發生未知錯誤: {e}"
    finally:
        if ssh_client:
            ssh_client.close() # 確保 SSH 連線被關閉

# --- Conversation Entry Point ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation and asks the user what to do."""
    if not await is_authorized(update):
        return ConversationHandler.END

    reply_keyboard = [["重推", "視頻下載"]]
    await update.message.reply_text(
        "請問要執行什麼工作？",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="選擇操作"
        ),
    )
    return SELECT_ACTION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    logger.info(f"User {update.effective_user.id} cancelled the operation.")
    await update.message.reply_text(
        "操作已取消，回到初始狀態。", reply_markup=ReplyKeyboardRemove()
    )
    # 將上下文的數據清除，確保下次從頭開始
    if "user_data" in context:
        context.user_data.clear()
    return ConversationHandler.END

# --- 重推 (Re-push) Flow ---

async def select_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks the user to select the push server or proceeds to video download."""
    if not await is_authorized(update):
        return ConversationHandler.END

    user_choice = update.message.text
    if user_choice == "重推":
        reply_keyboard = [["重推遊戲網視頻 (A)", "重推飛投視頻 (B)"], ["取消"]]
        await update.message.reply_text(
            "機器人詢問我要重推遊戲網視頻(VIDEO_PUSH_SERVER_IP_A)還是飛投視頻(VIDEO_PUSH_SERVER_IP_B)?",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, input_field_placeholder="選擇視頻類型"
            ),
        )
        return SELECT_PUSH_SERVER
    elif user_choice == "視頻下載":
        reply_keyboard = [["1", "2", "3", "4"], ["取消"]]
        await update.message.reply_text(
            "詢問要下載的桌台，請選擇數字 (1-4)：",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, input_field_placeholder="選擇桌台"
            ),
        )
        return SELECT_TABLE_FOR_DOWNLOAD
    else:
        await update.message.reply_text("無效的選擇，請重新選擇。", reply_markup=ReplyKeyboardRemove())
        return await start(update, context) # Go back to start

async def select_push_server(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the selected push server and asks for the table number."""
    if not await is_authorized(update):
        return ConversationHandler.END

    user_choice = update.message.text
    if user_choice == "重推遊戲網視頻 (A)":
        context.user_data["push_server_ip"] = VIDEO_PUSH_SERVER_IP_A
        context.user_data["server_type"] = "A"
    elif user_choice == "重推飛投視頻 (B)":
        context.user_data["push_server_ip"] = VIDEO_PUSH_SERVER_IP_B
        context.user_data["server_type"] = "B"
    else:
        await update.message.reply_text("無效的選擇，請重新選擇。", reply_markup=ReplyKeyboardRemove())
        return await start(update, context) # Go back to start

    reply_keyboard = [["1", "2", "3", "4"], ["取消"]]
    await update.message.reply_text(
        "請問要重推哪一桌？請選擇數字 (1-4)：",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="選擇桌號"
        ),
    )
    return SELECT_TABLE_FOR_PUSH

async def select_table_for_push(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the table number and asks for confirmation."""
    if not await is_authorized(update):
        return ConversationHandler.END

    table_number = update.message.text
    if not table_number.isdigit() or not (1 <= int(table_number) <= 4):
        await update.message.reply_text("無效的桌號，請輸入1到4之間的數字。", reply_markup=ReplyKeyboardRemove())
        return await select_push_server(update, context) # Go back to select push server if invalid table

    context.user_data["table_number"] = table_number
    server_type = context.user_data.get("server_type", "未知")

    reply_keyboard = [["是", "否"]]
    await update.message.reply_text(
        f"您是否確認要重推 {server_type} 伺服器的第 {table_number} 桌？",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="確認"
        ),
    )
    return CONFIRM_PUSH

async def confirm_push(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirms and executes the push command."""
    if not await is_authorized(update):
        return ConversationHandler.END

    confirmation = update.message.text
    if confirmation == "是":
        server_ip = context.user_data["push_server_ip"]
        table_number = context.user_data["table_number"]
        server_type = context.user_data["server_type"]

        command = f"docker restart streaming_script-ffmpeg_bk0{table_number}-1"
        await update.message.reply_text(f"正在 {server_ip} 上執行重推第 {table_number} 桌的指令，請稍候...")

        return_code, stdout, stderr = await run_ssh_command(
            host=server_ip,
            user=REMOTE_SERVER_USER,
            password=VIDEO_PUSH_SERVER_IP_PASSWORD,
            command=command
        )

        if return_code == 0:
            await update.message.reply_text(f"重推 {server_type} 伺服器第 {table_number} 桌成功！\nSTDOUT:\n{stdout}")
        else:
            error_message = stderr if stderr else "未知錯誤"
            await update.message.reply_text(f"重推 {server_type} 伺服器第 {table_number} 桌失敗！\n錯誤: {error_message}")
    else:
        await update.message.reply_text("已取消重推操作。")

    return await start(update, context) # Go back to start

# --- 視頻下載 (Video Download) Flow ---

async def select_table_for_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the table number for download and asks for the download time."""
    if not await is_authorized(update):
        return ConversationHandler.END

    table_number = update.message.text
    if not table_number.isdigit() or not (1 <= int(table_number) <= 4):
        await update.message.reply_text("無效的桌號，請輸入1到4之間的數字。", reply_markup=ReplyKeyboardRemove())
        return await select_action(update, context) # Go back to action selection if invalid table

    context.user_data["download_table_number"] = table_number
    await update.message.reply_text("請輸入要下載的時間點 (例如：`YYYY-MM-DD HH:MM` 或 `HH:MM`)。")
    return SELECT_DOWNLOAD_TIME

async def select_download_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finds video files based on time and asks for selection."""
    if not await is_authorized(update):
        return ConversationHandler.END

    time_input = update.message.text.strip()
    table_number = context.user_data["download_table_number"]
    
    search_dir = os.path.join(VIDEO_BASE_PATH, f"bk0{table_number}")
    
    target_datetime = None
    try:
        # 嘗試解析為完整的日期時間 YYYY-MM-DD HH:MM
        target_datetime = datetime.datetime.strptime(time_input, "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            # 嘗試解析為時間 HH:MM (假設是今天)
            current_date = datetime.date.today()
            target_time = datetime.datetime.strptime(time_input, "%H:%M").time()
            target_datetime = datetime.datetime.combine(current_date, target_time)
        except ValueError:
            await update.message.reply_text("無效的時間格式。請輸入 'YYYY-MM-DD HH:MM' 或 'HH:MM' 格式。", reply_markup=ReplyKeyboardRemove())
            return await select_table_for_download(update, context) # Go back to select table for download

    # Calculate time window: one hour before and one hour after
    start_time_window = target_datetime - datetime.timedelta(hours=1)
    end_time_window = target_datetime + datetime.timedelta(hours=1)

    # Use find command to search for files within the time range
    # This is a bit tricky with `find` alone for time *ranges*.
    # A more robust approach might be to list all files and then filter in Python,
    # or use a more complex `find` command with -newermt.
    # For now, let's list all files in the directory and filter in Python.

    list_command = f"find {search_dir} -type f -name 'output_*.mp4' -printf '%f\\n'" # Get only filename
    
    await update.message.reply_text(f"正在 {VIDEO_FILE_SERVER_IP} 的 {search_dir} 目錄下搜尋檔案，請稍候...")

    return_code, stdout, stderr = await run_ssh_command(
        host=VIDEO_FILE_SERVER_IP,
        user=REMOTE_SERVER_USER,
        password=VIDEO_PUSH_SERVER_IP_PASSWORD,
        command=list_command
    )

    if return_code != 0 and stderr:
        await update.message.reply_text(f"搜尋檔案時發生錯誤：\n{stderr}")
        return await start(update, context) # Go back to start
    
    all_files = [f for f in stdout.split('\n') if f.strip()]
    
    found_files_in_range = []
    # Regex to extract datetime from filename: output_YYYY-MM-DD_HH-MM-SS.mp4
    filename_regex = re.compile(r"output_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.mp4")

    for filename in all_files:
        match = filename_regex.match(filename)
        if match:
            date_part = match.group(1)
            time_part = match.group(2).replace('-', ':') # Change to HH:MM:SS
            try:
                file_datetime = datetime.datetime.strptime(f"{date_part}_{time_part}", "%Y-%m-%d_%H:%M:%S")
                if start_time_window <= file_datetime <= end_time_window:
                    found_files_in_range.append(os.path.join(search_dir, filename))
            except ValueError:
                logger.warning(f"Could not parse datetime from filename: {filename}")
                continue

    if not found_files_in_range:
        await update.message.reply_text("沒有找到符合條件的檔案。")
        return await start(update, context) # Go back to start

    context.user_data["found_files_for_selection"] = found_files_in_range
    
    file_options = [[os.path.basename(f)] for f in found_files_in_range]
    file_options.append(["取消"]) # Add cancel option
    
    await update.message.reply_text(
        "已找到以下檔案，請選擇一個進行下載：",
        reply_markup=ReplyKeyboardMarkup(
            file_options, one_time_keyboard=True, input_field_placeholder="選擇檔案"
        ),
    )
    return SELECT_FILE_FOR_DOWNLOAD

async def select_file_for_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the selected file for download and asks for confirmation."""
    if not await is_authorized(update):
        return ConversationHandler.END

    selected_filename = update.message.text
    found_files = context.user_data.get("found_files_for_selection", [])
    
    selected_full_path = None
    for f_path in found_files:
        if os.path.basename(f_path) == selected_filename:
            selected_full_path = f_path
            break
    
    if not selected_full_path:
        await update.message.reply_text("無效的檔案選擇，請重新選擇或取消。", reply_markup=ReplyKeyboardRemove())
        # Re-offer the file selection
        file_options = [[os.path.basename(f)] for f in found_files]
        file_options.append(["取消"])
        await update.message.reply_text(
            "請選擇一個檔案：",
            reply_markup=ReplyKeyboardMarkup(
                file_options, one_time_keyboard=True, input_field_placeholder="選擇檔案"
            ),
        )
        return SELECT_FILE_FOR_DOWNLOAD
    
    context.user_data["selected_file_to_download"] = selected_full_path

    reply_keyboard = [["是", "否"]]
    await update.message.reply_text(
        f"您是否確認要傳送檔案 `{selected_filename}`？",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="確認傳送"
        ),
    )
    return CONFIRM_DOWNLOAD


async def confirm_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Downloads, uploads, and cleans up the selected file."""
    if not await is_authorized(update):
        return ConversationHandler.END

    confirmation = update.message.text
    if confirmation == "是":
        remote_file_path = context.user_data.get("selected_file_to_download")
        if not remote_file_path:
            await update.message.reply_text("沒有找到要下載的檔案。")
            return await start(update, context)

        file_name = os.path.basename(remote_file_path)
        local_path = os.path.join("/tmp", file_name) # 下載到 /tmp 目錄
        
        await update.message.reply_text(f"開始下載檔案 `{file_name}` 到機器人本地...")

        try:
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(hostname=VIDEO_FILE_SERVER_IP, username=REMOTE_SERVER_USER, password=VIDEO_PUSH_SERVER_IP_PASSWORD, timeout=10)
            
            sftp_client = ssh_client.open_sftp()
            sftp_client.get(remote_file_path, local_path)
            sftp_client.close()
            ssh_client.close()

            await update.message.reply_text(f"檔案 `{file_name}` 下載完成。開始上傳至 Telegram...")
            
            try:
                with open(local_path, 'rb') as f:
                    await update.message.reply_document(document=f)
                await update.message.reply_text(f"檔案 `{file_name}` 上傳成功。")
            except Exception as e:
                await update.message.reply_text(f"上傳檔案 `{file_name}` 時發生錯誤：{e}")
                logger.error(f"Error uploading {local_path} to Telegram: {e}")
            finally:
                if os.path.exists(local_path):
                    os.remove(local_path)
                    logger.info(f"Deleted local file: {local_path}")
                await update.message.reply_text("本地檔案已清除。")

        except paramiko.AuthenticationException:
            await update.message.reply_text(f"下載檔案 `{file_name}` 失敗：認證錯誤，請檢查伺服器設定。")
            logger.error(f"SFTP Authentication failed for {REMOTE_SERVER_USER}@{VIDEO_FILE_SERVER_IP}.")
        except paramiko.SSHException as e:
            await update.message.reply_text(f"下載檔案 `{file_name}` 失敗：SSH 連線或 SFTP 錯誤: {e}")
            logger.error(f"SFTP connection/transfer error for {file_name}: {e}")
        except FileNotFoundError:
            await update.message.reply_text(f"下載檔案 `{file_name}` 失敗：遠端檔案不存在或路徑錯誤。")
            logger.error(f"Remote file not found: {remote_file_path}")
        except Exception as e:
            await update.message.reply_text(f"下載檔案 `{file_name}` 時發生未知錯誤：{e}")
            logger.error(f"Error downloading {file_name} via SFTP: {e}")
    else:
        await update.message.reply_text("已取消視訊下載操作。")

    return await start(update, context) # Go back to start

def main() -> None:
    """Start the bot."""
    # Parse command line arguments first
    parser = argparse.ArgumentParser(description="Telegram Bot for server operations.")
    parser.add_argument("--token", required=True, help="Telegram Bot Token")
    parser.add_argument("--user", required=True, help="Remote Server User (e.g., root)")
    parser.add_argument("--VIDEO_PUSH_SERVER_IP_A", required=True, help="IP of Video Push Server A")
    parser.add_argument("--VIDEO_PUSH_SERVER_IP_B", required=True, help="IP of Video Push Server B")
    parser.add_argument("--VIDEO_FILE_SERVER_IP", required=True, help="IP of Video File Server")
    parser.add_argument("--password", required=True, help="Password for SSH connections")
    parser.add_argument("--auth_id", required=True, help="Comma-separated authorized user IDs")
    parser.add_argument("--video_base_path", default="/home/video", help="Base path for video files on the remote server")

    args = parser.parse_args()

    global TELEGRAM_BOT_TOKEN, REMOTE_SERVER_USER, VIDEO_PUSH_SERVER_IP_A, \
           VIDEO_PUSH_SERVER_IP_B, VIDEO_FILE_SERVER_IP, VIDEO_PUSH_SERVER_IP_PASSWORD, \
           AUTHORIZED_USER_IDS, VIDEO_BASE_PATH
    
    TELEGRAM_BOT_TOKEN = args.token
    REMOTE_SERVER_USER = args.user
    VIDEO_PUSH_SERVER_IP_A = args.VIDEO_PUSH_SERVER_IP_A
    VIDEO_PUSH_SERVER_IP_B = args.VIDEO_PUSH_SERVER_IP_B
    VIDEO_FILE_SERVER_IP = args.VIDEO_FILE_SERVER_IP
    VIDEO_PUSH_SERVER_IP_PASSWORD = args.password
    # 將逗號分隔的字符串解析為列表
    AUTHORIZED_USER_IDS = [uid.strip() for uid in args.auth_id.split(',') if uid.strip()]
    VIDEO_BASE_PATH = args.video_base_path

    if not AUTHORIZED_USER_IDS:
        logger.error("No authorized user IDs provided. The bot will not respond to anyone.")
    else:
        logger.info(f"Bot starting with authorized users: {AUTHORIZED_USER_IDS}")

    # Create the Application and pass your bot's token.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Define conversation handler with states
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_ACTION: [
                MessageHandler(
                    filters.Regex("^(重推|視頻下載)$") & ~filters.COMMAND, select_action
                ),
                CommandHandler("cancel", cancel) # Allow cancel at this step
            ],
            SELECT_PUSH_SERVER: [
                MessageHandler(
                    filters.Regex("^(重推遊戲網視頻 \(A\)|重推飛投視頻 \(B\))$") & ~filters.COMMAND, select_push_server
                ),
                CommandHandler("cancel", cancel)
            ],
            SELECT_TABLE_FOR_PUSH: [
                MessageHandler(
                    filters.Regex("^[1-4]$") & ~filters.COMMAND, select_table_for_push
                ),
                CommandHandler("cancel", cancel)
            ],
            CONFIRM_PUSH: [
                MessageHandler(
                    filters.Regex("^(是|否)$") & ~filters.COMMAND, confirm_push
                ),
                CommandHandler("cancel", cancel)
            ],
            SELECT_TABLE_FOR_DOWNLOAD: [
                MessageHandler(
                    filters.Regex("^[1-4]$") & ~filters.COMMAND, select_table_for_download
                ),
                CommandHandler("cancel", cancel)
            ],
            SELECT_DOWNLOAD_TIME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, select_download_time
                ),
                CommandHandler("cancel", cancel)
            ],
            SELECT_FILE_FOR_DOWNLOAD: [ # New handler for file selection
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, select_file_for_download
                ),
                CommandHandler("cancel", cancel)
            ],
            CONFIRM_DOWNLOAD: [
                MessageHandler(
                    filters.Regex("^(是|否)$") & ~filters.COMMAND, confirm_download
                ),
                CommandHandler("cancel", cancel)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)], # Global fallback to cancel
        allow_reentry=True # 允許用戶在對話中再次發送 /start 來重新開始
    )

    application.add_handler(conv_handler)

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()