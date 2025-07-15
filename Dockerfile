# Dockerfile

# 使用 Python 官方的 slim 版映像檔作為基礎，這比完整版更小，適合生產環境。
# python:3.10-slim-bookworm 是一個不錯的選擇，基於 Debian Bookworm，提供良好的兼容性。
FROM python:3.10-slim-bookworm

# 設定工作目錄，所有後續操作都將在這個目錄下進行。
WORKDIR /app

# 複製 requirements.txt 到容器中。
# 這樣做可以讓 Docker 在 requirements.txt 沒有改變時，快取 pip install 的結果。
COPY requirements.txt .

# 安裝所有 Python 依賴。
# 使用 --no-cache-dir 可以避免產生不必要的 pip 快取，進一步縮小映像檔。
# 注意：這裡假設 requirements.txt 包含了 telegram-python-bot 和其他所有需要的庫。
RUN pip install --no-cache-dir -r requirements.txt

# 複製所有應用程式的程式碼到容器中。
# 這一層會在 requirements.txt 或其他文件改變時重新建置，但不會重新安裝依賴。
COPY . .

# 設定容器啟動時的預設命令。
# ENTRYPOINT 用於設定容器啟動時執行的命令，CMD 則為其提供預設參數。
# 這裡我們使用 entrypoint.sh 腳本來啟動我們的 Python 應用程式，
# 這樣可以在啟動時動態傳入參數。
# 請確保 entrypoint.sh 檔案具有執行權限。
ENTRYPOINT ["./entrypoint.sh"]

# CMD 用於為 ENTRYPOINT 提供預設參數。
# 這些參數可以被 docker run 命令後面的參數覆寫。
# 例如，如果你不傳遞任何參數給 docker run，它將使用這裡的預設值。
# 但我們會在 docker-compose.yml 中直接指定完整的命令。
CMD ["python", "cmdtgbot.py"]