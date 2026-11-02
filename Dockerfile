# ==============================================================================
# Mini AI Business Intelligence Assistant - Production Containerfile
# ==============================================================================
FROM python:3.11-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure data directory exists
RUN mkdir -p /app/data /app/data/backups

# Expose FastAPI (8000) and Streamlit (8501)
EXPOSE 8000 8501

# Default environment settings
ENV PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////app/data/bi_assistant.db \
    CSV_DATA_PATH=/app/data/sales.csv

# Default command runs the backend via uvicorn
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
