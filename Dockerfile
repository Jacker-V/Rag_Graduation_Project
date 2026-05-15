FROM python:3.10-slim

WORKDIR /app

# Runtime OS deps (torch + scientific stack)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for layer caching
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data/data data/chat_history data/chroma data/huggingface data/cache

ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/app/data/huggingface
ENV TRANSFORMERS_CACHE=/app/data/huggingface

EXPOSE 7860 7861

CMD ["python", "run_admin_web.py"]