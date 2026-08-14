FROM python:3.12-slim

WORKDIR /app

# Dependencias del sistema para psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Universal Service Tags (alineados con OTel Resource)
ENV SERVICE_NAME=service-a
ENV APP_VERSION=1.0.0
ENV ENVIRONMENT=production
ENV PROMETHEUS_PORT=9090

# Puerto de la app FastAPI
EXPOSE 8000
# Puerto de métricas Prometheus
EXPOSE 9090

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
