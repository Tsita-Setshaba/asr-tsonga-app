FROM python:3.11-slim

WORKDIR /app

# System deps needed by torchaudio/librosa for audio decoding
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hugging Face Spaces expects the app to listen on port 7860
ENV PORT=7860
EXPOSE 7860

CMD ["python", "app.py"]
