# Use an official Python runtime as a parent image.
# We're going with a slim-buster image to keep the image size down.
FROM python:3.9-slim-buster

# Set the working directory in the container.
WORKDIR /app

# Copy the requirements file first to leverage Docker's build cache.
# This is crucial for faster rebuilds if only the script changes.
COPY requirements.txt .

# Install any needed packages specified in requirements.txt.
# Using --no-cache-dir reduces the image size by not storing build-time cache.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot script into the container at /app.
COPY cmdtgbot.py .

# Create the /home/video directory inside the container.
# This directory will be used as a mount point for the host volume.
# Setting appropriate permissions is good practice.
RUN mkdir -p /home/video && chmod -R 755 /home/video

# Command to run the bot.
# We're using environment variables for sensitive data and configuration.
# This is far more secure and flexible than hardcoding into the Dockerfile or command.
CMD ["python", "cmdtgbot.py", \
    "--token", "${TELEGRAM_BOT_TOKEN}", \
    "--user", "${REMOTE_SERVER_USER}", \
    "--ip", "${REMOTE_PUSH_SERVER_IP}", \
    "--password", "${REMOTE_PUSH_SERVER_IP_PASSWORD}", \
    "--video_path", "${VIDEO_BASE_PATH}", \
    "--auth_id", "${AUTHORIZED_USER_ID}"]