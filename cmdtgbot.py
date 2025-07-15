# -*- coding: utf-8 -*-
import argparse
import logging
import os
import re
import asyncio
from datetime import datetime, timedelta

# 引入 Telegram Bot 相關庫
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)

# 引入 Paramiko 庫用於 SSH 連線
# 如果尚未安裝，請執行：pip install paramiko
import paramiko

# 設定日誌記錄
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# 定義對話狀態
CHOOSING_TASK, RESTART_TABLE, RESTART_CONFIRM, DOWNLOAD_TABLE, DOWNLOAD_TIME, DOWNLOAD_CONFIRM_SEND = range(6)

# 全局變數，用於儲存從命令列參數獲取的值
TELEGRAM_BOT_TOKEN = None
REMOTE_SERVER_USER = None
REMOTE_PUSH_SERVER_IP = None
REMOTE_PUSH_SERVER_IP_PASSWORD = None
VIDEO_BASE_PATH = None
AUTHORIZED_USER_ID = None # 這裡需要填寫您自己的 Telegram User ID，請參閱下方說明如何獲取

# --- 輔助函數 ---

def is_authorized(update: Update) -> bool:
    """
    檢查使用者是否為授權使用者。
    """
    if update.effective_user.id == AUTHORIZED_USER_ID:
        return True
    logger.warning(f"未授權的使用者嘗試訪問: {update.effective_user.id}")
    update.message.reply_text("抱歉，您沒有權限執行此操作。")
    return False

async def run_remote_command(command: str) -> tuple[int, str, str]:
    """
    使用 Paramiko 執行遠端 SSH 命令。
    返回 (exit_status, stdout, stderr)。
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy()) # 自動添加主機金鑰，首次連線時可能需要確認
    try:
        logger.info(f"嘗試連線到 {REMOTE_PUSH_SERVER_IP} 並執行命令: {command}")
        client.connect(
            hostname=REMOTE_PUSH_SERVER_IP,
            username=REMOTE_SERVER_USER,
            password=REMOTE_PUSH_SERVER_IP_PASSWORD,
            timeout=10 # 連線逾時設定
        )
        stdin, stdout, stderr = client.exec_command(command)
        exit_status = stdout.channel.recv_exit_status() # 等待命令執行完成並獲取退出狀態
        output = stdout.read().decode('utf-8').strip()
        error = stderr.read().decode('utf-8').strip()
        logger.info(f"命令執行完成，退出狀態: {exit_status}")
        if output:
            logger.info(f"標準輸出: {output}")
        if error:
            logger.error(f"標準錯誤: {error}")
        return exit_status, output, error
    except paramiko.AuthenticationException:
        logger.error("SSH 認證失敗，請檢查使用者名稱和密碼。")
        return -1, "", "SSH 認證失敗。"
    except paramiko.SSHException as e:
        logger.error(f"SSH 連線或執行命令時發生錯誤: {e}")
        return -1, "", f"SSH 錯誤: {e}"
    except Exception as e:
        logger.error(f"執行遠端命令時發生未知錯誤: {e}")
        return -1, "", f"未知錯誤: {e}"
    finally:
        client.close()

async def download_remote_file(remote_path: str, local_path: str) -> bool:
    """
    使用 Paramiko 的 SFTP 客戶端從遠端伺服器下載檔案。
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        logger.info(f"嘗試連線到 {REMOTE_PUSH_SERVER_IP} 並下載檔案: {remote_path} 到 {local_path}")
        client.connect(
            hostname=REMOTE_PUSH_SERVER_IP,
            username=REMOTE_SERVER_USER,
            password=REMOTE_PUSH_SERVER_IP_PASSWORD,
            timeout=10
        )
        sftp = client.open_sftp()
        sftp.get(remote_path, local_path)
        sftp.close()
        logger.info(f"檔案下載成功: {remote_path}")
        return True
    except paramiko.AuthenticationException:
        logger.error("SFTP 認證失敗，請檢查使用者名稱和密碼。")
        return False
    except paramiko.SSHException as e:
        logger.error(f"SFTP 連線或下載檔案時發生錯誤: {e}")
        return False
    except FileNotFoundError:
        logger.error(f"遠端檔案不存在: {remote_path}")
        return False
    except Exception as e:
        logger.error(f"下載遠端檔案時發生未知錯誤: {e}")
        return False
    finally:
        client.close()

# --- 命令處理器 ---

async def start(update: Update, context: Application) -> int:
    """
    處理 /start 命令，啟動對話。
    """
    if not is_authorized(update):
        return ConversationHandler.END

    reply_keyboard = [["重推", "視頻下載"]]
    await update.message.reply_text(
        "請問要執行什麼工作？",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="請選擇工作："
        ),
    )
    return CHOOSING_TASK

async def choose_task(update: Update, context: Application) -> int:
    """
    處理使用者選擇的工作類型。
    """
    if not is_authorized(update):
        return ConversationHandler.END

    text = update.message.text
    context.user_data["choice"] = text

    if text == "重推":
        reply_keyboard = [["1", "2", "3", "4"]]
        await update.message.reply_text(
            "請問要重推哪一桌？(1-4)",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, input_field_placeholder="請選擇桌號："
            ),
        )
        return RESTART_TABLE
    elif text == "視頻下載":
        reply_keyboard = [["1", "2", "3", "4"]]
        await update.message.reply_text(
            "請問要下載哪一桌的視頻？(1-4)",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, input_field_placeholder="請選擇桌號："
            ),
        )
        return DOWNLOAD_TABLE
    else:
        await update.message.reply_text("無效的選項，請重新選擇。", reply_markup=ReplyKeyboardRemove())
        return await start(update, context) # 返回初始狀態

async def restart_table(update: Update, context: Application) -> int:
    """
    處理使用者選擇的重推桌號。
    """
    if not is_authorized(update):
        return ConversationHandler.END

    table_num = update.message.text
    if not table_num.isdigit() or not (1 <= int(table_num) <= 4):
        await update.message.reply_text("無效的桌號，請輸入 1 到 4 之間的數字。")
        return RESTART_TABLE # 保持在當前狀態，讓使用者重新輸入

    context.user_data["table_num"] = table_num
    reply_keyboard = [["是", "否"]]
    await update.message.reply_text(
        f"您確定要重推 {table_num} 號桌嗎？",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="請確認："
        ),
    )
    return RESTART_CONFIRM

async def restart_confirm(update: Update, context: Application) -> int:
    """
    確認重推操作並執行遠端命令。
    """
    if not is_authorized(update):
        return ConversationHandler.END

    confirmation = update.message.text
    table_num = context.user_data["table_num"]

    if confirmation == "是":
        command = f"docker restart streaming_script-ffmpeg_bk0{table_num}-1"
        full_command = f"ssh {REMOTE_SERVER_USER}@{REMOTE_PUSH_SERVER_IP} {command}"
        await update.message.reply_text(f"正在執行重推命令：`{full_command}`...", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
        
        exit_status, stdout, stderr = await run_remote_command(command)

        if exit_status == 0:
            await update.message.reply_text(f"{table_num} 號桌重推成功！\n輸出：\n`{stdout}`", parse_mode="Markdown")
        else:
            error_message = f"{table_num} 號桌重推失敗！\n錯誤：\n`{stderr}`"
            if stdout:
                error_message += f"\n輸出：\n`{stdout}`"
            await update.message.reply_text(error_message, parse_mode="Markdown")
    else:
        await update.message.reply_text("已取消重推操作。", reply_markup=ReplyKeyboardRemove())

    return await start(update, context) # 返回初始狀態

async def download_table(update: Update, context: Application) -> int:
    """
    處理使用者選擇的視頻下載桌號。
    """
    if not is_authorized(update):
        return ConversationHandler.END

    table_num = update.message.text
    if not table_num.isdigit() or not (1 <= int(table_num) <= 4):
        await update.message.reply_text("無效的桌號，請輸入 1 到 4 之間的數字。")
        return DOWNLOAD_TABLE # 保持在當前狀態，讓使用者重新輸入

    context.user_data["table_num"] = table_num
    await update.message.reply_text(
        "請輸入要下載視頻的時間點 (例如: 2023-10-27 15:30:00)。\n"
        "我們將搜尋該時間點前後約 1 分鐘的檔案。",
        reply_markup=ReplyKeyboardRemove()
    )
    return DOWNLOAD_TIME

async def download_time(update: Update, context: Application) -> int:
    """
    處理使用者輸入的下載時間點，並搜尋檔案。
    """
    if not is_authorized(update):
        return ConversationHandler.END

    time_str = update.message.text
    try:
        # 嘗試解析時間字串
        search_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        await update.message.reply_text("時間格式無效，請使用 YYYY-MM-DD HH:MM:SS 格式。")
        return DOWNLOAD_TIME # 保持在當前狀態，讓使用者重新輸入

    table_num = context.user_data["table_num"]
    remote_video_dir = os.path.join(VIDEO_BASE_PATH, f"bk{table_num}")

    # 構建 find 命令，搜尋指定時間點前後約 1 分鐘的 .mp4 檔案
    # 注意：find 的 -newermt 選項是基於修改時間。
    # 我們將搜尋從 search_time - 1 分鐘 到 search_time + 1 分鐘 之間的檔案。
    start_time_str = (search_time - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    end_time_str = (search_time + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")

    # 為了避免 find 指令中的空格問題，使用單引號包圍時間字串
    find_command = (
        f"find '{remote_video_dir}' -type f -name '*.mp4' "
        f"-newermt '{start_time_str}' ! -newermt '{end_time_str}'"
    )
    
    await update.message.reply_text(f"正在搜尋遠端伺服器上的視頻檔案，請稍候...", reply_markup=ReplyKeyboardRemove())
    
    exit_status, stdout, stderr = await run_remote_command(find_command)

    if exit_status == 0 and stdout:
        found_files = stdout.splitlines()
        context.user_data["found_files"] = found_files
        file_list_str = "\n".join([os.path.basename(f) for f in found_files])
        reply_keyboard = [["是", "否"]]
        await update.message.reply_text(
            f"找到以下檔案：\n`{file_list_str}`\n\n是否要傳送這些檔案？",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, input_field_placeholder="請確認："
            ),
        )
        return DOWNLOAD_CONFIRM_SEND
    else:
        await update.message.reply_text(
            f"未找到符合條件的視頻檔案，或搜尋時發生錯誤。\n錯誤訊息：`{stderr}`",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return await start(update, context) # 返回初始狀態

async def download_confirm_send(update: Update, context: Application) -> int:
    """
    確認是否傳送檔案，並執行下載、上傳和刪除操作。
    """
    if not is_authorized(update):
        return ConversationHandler.END

    confirmation = update.message.text
    found_files = context.user_data.get("found_files", [])

    if confirmation == "是" and found_files:
        await update.message.reply_text("正在下載並傳送檔案，請稍候...", reply_markup=ReplyKeyboardRemove())
        
        local_download_dir = "./temp_downloads"
        os.makedirs(local_download_dir, exist_ok=True) # 確保本地下載目錄存在

        all_downloads_successful = True
        for remote_file_path in found_files:
            local_file_name = os.path.basename(remote_file_path)
            local_file_path = os.path.join(local_download_dir, local_file_name)

            if await download_remote_file(remote_file_path, local_file_path):
                try:
                    await update.message.reply_document(document=open(local_file_path, 'rb'))
                    logger.info(f"檔案 {local_file_name} 已上傳。")
                except Exception as e:
                    logger.error(f"上傳檔案 {local_file_name} 時發生錯誤: {e}")
                    await update.message.reply_text(f"上傳檔案 {local_file_name} 失敗。")
                    all_downloads_successful = False
                finally:
                    # 無論上傳成功與否，都嘗試刪除本地檔案
                    if os.path.exists(local_file_path):
                        os.remove(local_file_path)
                        logger.info(f"本地檔案 {local_file_name} 已刪除。")
            else:
                all_downloads_successful = False
                await update.message.reply_text(f"下載遠端檔案 {remote_file_path} 失敗。")

        # 清理本地下載目錄 (如果為空)
        if not os.listdir(local_download_dir):
            os.rmdir(local_download_dir)

        if all_downloads_successful:
            await update.message.reply_text("所有視頻檔案已成功傳送並清理。")
        else:
            await update.message.reply_text("部分檔案傳送失敗，請檢查日誌。")

    else:
        await update.message.reply_text("已取消視頻傳送。", reply_markup=ReplyKeyboardRemove())

    return await start(update, context) # 返回初始狀態

async def cancel(update: Update, context: Application) -> int:
    """
    處理 /cancel 命令，結束對話。
    """
    if not is_authorized(update):
        return ConversationHandler.END

    await update.message.reply_text(
        "操作已取消。", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def handle_unauthorized(update: Update, context: Application):
    """
    處理未授權使用者的訊息。
    """
    if not is_authorized(update):
        # 訊息已在 is_authorized 函數中處理，這裡只需確保不進入其他對話流程
        return

# --- 主函數 ---

def main():
    """
    主函數，啟動 Telegram Bot。
    """
    global TELEGRAM_BOT_TOKEN, REMOTE_SERVER_USER, REMOTE_PUSH_SERVER_IP, REMOTE_PUSH_SERVER_IP_PASSWORD, VIDEO_BASE_PATH, AUTHORIZED_USER_ID

    parser = argparse.ArgumentParser(description="Telegram Bot for remote server management.")
    parser.add_argument("--token", required=True, help="Your Telegram Bot Token.")
    parser.add_argument("--user", required=True, help="Remote server SSH username (e.g., root).")
    parser.add_argument("--ip", required=True, help="Remote server IP address.")
    parser.add_argument("--password", required=True, help="Remote server SSH password.")
    parser.add_argument("--video_path", required=True, help="Base path for video files on the remote server (e.g., /home/video).")
    parser.add_argument("--auth_id", type=int, required=True, help="Your Telegram User ID (integer) for authorization.")

    args = parser.parse_args()

    TELEGRAM_BOT_TOKEN = args.token
    REMOTE_SERVER_USER = args.user
    REMOTE_PUSH_SERVER_IP = args.ip
    REMOTE_PUSH_SERVER_IP_PASSWORD = args.password
    VIDEO_BASE_PATH = args.video_path
    AUTHORIZED_USER_ID = args.auth_id

    # 創建 Application 並傳入 Bot Token
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 定義對話處理器
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_TASK: [
                MessageHandler(filters.Regex("^(重推|視頻下載)$"), choose_task)
            ],
            RESTART_TABLE: [
                MessageHandler(filters.Regex("^[1-4]$"), restart_table)
            ],
            RESTART_CONFIRM: [
                MessageHandler(filters.Regex("^(是|否)$"), restart_confirm)
            ],
            DOWNLOAD_TABLE: [
                MessageHandler(filters.Regex("^[1-4]$"), download_table)
            ],
            DOWNLOAD_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, download_time)
            ],
            DOWNLOAD_CONFIRM_SEND: [
                MessageHandler(filters.Regex("^(是|否)$"), download_confirm_send)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.ALL, handle_unauthorized)],
    )

    application.add_handler(conv_handler)

    # 處理未授權使用者的所有其他訊息
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_unauthorized))

    # 啟動 Bot
    logger.info("Bot 正在啟動...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Bot 已停止。")

if __name__ == "__main__":
    main()
