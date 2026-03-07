FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y \
    portaudio19-dev libsndfile1 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY src/ ./src/
COPY configs/ ./configs/

EXPOSE 3001

CMD ["python", "-m", "src.core.omnimind"]
