FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 git git-lfs && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt service/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r service/requirements.txt \
    && pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY . .
# base weights are fetched on first use; ship fine-tuned checkpoints in weights/
EXPOSE 8000
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
