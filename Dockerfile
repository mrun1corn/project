FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies including ffmpeg and networking tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    bash \
    build-essential \
    libffi-dev \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

CMD ["python", "src/main.py"]
