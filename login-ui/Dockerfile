FROM python:3.14-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    flask \
    flask-sock \
    simple-websocket \
    moomoo-api

COPY app.py .

CMD ["python", "app.py"]
