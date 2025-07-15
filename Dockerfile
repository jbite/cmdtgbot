# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for paramiko (SSH)
# You might need to add more if specific SSH features are used or if your Linux distro
# requires different packages for building certain Python wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Grant execute permissions to the entrypoint script
RUN chmod +x /app/entrypoint.sh

# Command to run the entrypoint script
# CMD will execute the entrypoint.sh script which then runs your Python application.
# ENTRYPOINT is used here to ensure your script is always run when the container starts,
# and any CMD arguments are appended to it.
CMD ["./entrypoint.sh"]

# No CMD here as entrypoint.sh handles the command line args