FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV SERVICE_NAME=service-b
ENV APP_VERSION=1.0.0
ENV ENVIRONMENT=production
ENV PROMETHEUS_PORT=9091

EXPOSE 8001
EXPOSE 9091

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
