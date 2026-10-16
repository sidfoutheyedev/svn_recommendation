# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HF_HOME=/models

# Install Python dependencies
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install \
      --index-url https://download.pytorch.org/whl/cpu \
      --extra-index-url https://pypi.org/simple \
      -r requirements.txt

# Copy modules required for model download and embedding
COPY app/__init__.py app/__init__.py
COPY app/config.py app/config.py
COPY app/database.py app/database.py
COPY download_model.py .
COPY embedding_job.py .

# Download the model
RUN python download_model.py

# Generate embeddings
RUN python embedding_job.py

# Copy the remaining application code
COPY . .

# Application port
EXPOSE 8000

# Start the FastAPI application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]