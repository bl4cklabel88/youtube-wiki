FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure data directory exists
RUN mkdir -p /app/data/articles /app/data/transcripts

EXPOSE 8000

# Default command for the web worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
