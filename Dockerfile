# Use a lightweight base image with Python
FROM python:3.9-slim-buster

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot script and entrypoint script into the container
COPY cmdtgbot.py .
COPY entrypoint.sh .

# Give execution rights to the entrypoint script
RUN chmod +x entrypoint.sh

# Expose any ports if your bot needed to listen for incoming connections (not typical for Telegram bots)
# EXPOSE 8080 

# Command to run the entrypoint script
ENTRYPOINT ["./entrypoint.sh"]