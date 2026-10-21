# Озвучка Stevens: Silero TTS, голос aidar. Только CPU, модель докачивается при первом запуске в том /models.
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY normalize.py app.py ./
ENV MODELS_DIR=/models
EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
