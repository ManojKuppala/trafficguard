# Use Python 3.10 slim as the base image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies required for OpenCV and EasyOCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY venv/backend ./backend
COPY venv/frontend ./frontend

# Create upload and results directories inside the container's static folder
RUN mkdir -p frontend/static/uploads frontend/static/results

# Expose the Hugging Face Spaces default port (7860)
EXPOSE 7860

# Run the Flask app on port 7860 (Hugging Face expects port 7860)
CMD ["python", "backend/app.py"]
