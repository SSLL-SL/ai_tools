FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV GAMES_JSON_PATH=/data/GAMES.json
ENV CONFIG_PATH=/data/config.json
ENV QUEUE_PATH=/data/queue.json

EXPOSE 5050

CMD ["python3", "app.py"]
