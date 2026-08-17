"""
service-b: FastAPI — Servicio de inventario.

Recibe llamadas de service-a y consulta PostgreSQL. Cuando OpenTelemetry está
habilitado continúa el trace distribuido mediante W3C TraceContext.
"""

import logging
import os
import random
import time
from contextlib import asynccontextmanager

import psycopg2
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import start_http_server
from pythonjsonlogger import jsonlogger

# ── OpenTelemetry API/SDK ────────────────────────────────────────────────────
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


# ── Configuración desde variables de entorno ─────────────────────────────────
OTEL_ENDPOINT = os.getenv(
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "http://otel-collector:4317",
)
DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://app:secret@postgres:5432/appdb",
)
PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", "9091"))
ENV = os.getenv("ENVIRONMENT", "production")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")

# ── 5.5 Baseline real ────────────────────────────────────────────────────────
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "true").strip().lower() == "true"

resource = None
tracer_provider = None
meter_provider = None
logger_provider = None


# ── 5.1 / 5.2 / 5.4 / 5.5 Inicialización OpenTelemetry ──────────────────────
if OTEL_ENABLED:
    resource = Resource.create(
        {
            SERVICE_NAME: "service-b",
            SERVICE_VERSION: APP_VERSION,
            "deployment.environment": ENV,
            "cloud.provider": os.getenv("CLOUD_PROVIDER", "aws"),
            "host.name": os.getenv("HOSTNAME", "local"),
        }
    )

    # Logs OTLP -> Collector.
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(
                endpoint=OTEL_ENDPOINT,
                insecure=True,
            )
        )
    )
    set_logger_provider(logger_provider)

    # Trazas OTLP con IDs compatibles con AWS X-Ray.
    tracer_provider = TracerProvider(
        resource=resource,
        id_generator=AwsXRayIdGenerator(),
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=OTEL_ENDPOINT,
                insecure=True,
            )
        )
    )
    trace.set_tracer_provider(tracer_provider)

    # Métricas: solo Prometheus scraping; no se duplica con OTLPMetricExporter.
    prometheus_reader = PrometheusMetricReader()
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[prometheus_reader],
    )
    metrics.set_meter_provider(meter_provider)

    # service-b no usa httpx como cliente, por eso NO usa HTTPXClientInstrumentor.
    # Psycopg2Instrumentor().instrument(tracer_provider=tracer_provider)
    
    Psycopg2Instrumentor().instrument(
        tracer_provider=tracer_provider,
        skip_dep_check=True,
    )



tracer = trace.get_tracer("service-b", APP_VERSION)
meter = metrics.get_meter("service-b", APP_VERSION)


# ── 5.3 Instrumentos HTTP homogéneos ─────────────────────────────────────────
http_requests_total = meter.create_counter(
    "http_requests_total",
    description="Total de solicitudes HTTP recibidas",
    unit="1",
)
http_request_duration = meter.create_histogram(
    "http_request_duration_seconds",
    description="Duración de solicitudes HTTP",
    unit="s",
)
active_requests = meter.create_up_down_counter(
    "http_active_requests",
    description="Solicitudes HTTP activas",
    unit="1",
)

# Métricas específicas de inventario.
inventory_requests = meter.create_counter(
    "inventory_requests_total",
    description="Total de consultas de inventario procesadas",
    unit="1",
)
inventory_query_duration = meter.create_histogram(
    "inventory_query_duration_seconds",
    description="Latencia de consultas de inventario a PostgreSQL",
    unit="s",
)
cache_hits = meter.create_counter(
    "inventory_cache_hits_total",
    description="Cache hits en consultas de inventario",
    unit="1",
)


# ── 5.4 Logging estructurado JSON con trace_id/span_id ───────────────────────
class OtelJsonFormatter(jsonlogger.JsonFormatter):
    """Agrega contexto OTel y metadatos del servicio a cada log JSON."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            log_record["trace_id"] = format(ctx.trace_id, "032x")
            log_record["span_id"] = format(ctx.span_id, "016x")

        log_record["service"] = "service-b"
        log_record["version"] = APP_VERSION
        log_record["environment"] = ENV


json_formatter = OtelJsonFormatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s"
)

# stdout -> ECS awslogs -> CloudWatch Logs.
stdout_handler = logging.StreamHandler()
stdout_handler.setFormatter(json_formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()
root_logger.addHandler(stdout_handler)

# OTLP -> Collector únicamente cuando OTel está habilitado.
if OTEL_ENABLED and logger_provider is not None:
    otel_log_handler = LoggingHandler(
        level=logging.INFO,
        logger_provider=logger_provider,
    )
    otel_log_handler.setFormatter(json_formatter)
    root_logger.addHandler(otel_log_handler)

logger = logging.getLogger("service-b")


# ── Cache en memoria ─────────────────────────────────────────────────────────
_inventory_cache: dict[str, dict] = {}


def get_db_connection():
    return psycopg2.connect(DB_DSN)


# ── Ciclo de vida FastAPI ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    if OTEL_ENABLED:
        start_http_server(PROMETHEUS_PORT)
        logger.info(
            "Prometheus metrics server started",
            extra={"port": PROMETHEUS_PORT, "otel_enabled": True},
        )
    else:
        logger.info(
            "OpenTelemetry disabled - baseline mode",
            extra={"otel_enabled": False},
        )

    yield

    if tracer_provider is not None:
        tracer_provider.shutdown()
    if meter_provider is not None:
        meter_provider.shutdown()
    if logger_provider is not None:
        logger_provider.shutdown()


# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Service B",
    description="Microservicio de inventario — OTel end-to-end lab",
    version=APP_VERSION,
    lifespan=lifespan,
)


# ── 5.3 Middleware HTTP para SLIs ────────────────────────────────────────────
async def record_http_slis(request: Request, call_next):
    started_at = time.perf_counter()
    active_attributes = {"method": request.method}

    active_requests.add(1, active_attributes)
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route_object = request.scope.get("route")
        route_path = getattr(route_object, "path", request.url.path)

        metric_attributes = {
            "method": request.method,
            "route": route_path,
            "status": str(status_code),
        }
        duration_seconds = time.perf_counter() - started_at

        http_requests_total.add(1, metric_attributes)
        http_request_duration.record(duration_seconds, metric_attributes)
        active_requests.add(-1, active_attributes)


if OTEL_ENABLED:
    # El middleware forma parte del costo de observabilidad y se omite en baseline.
    app.middleware("http")(record_http_slis)

    # FastAPI instrumentado después de crear `app`.
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "service-b",
        "otel_enabled": OTEL_ENABLED,
    }


@app.get("/inventory/{product_id}")
async def get_inventory(product_id: str):
    """Retorna disponibilidad de inventario para un producto."""

    started_at = time.perf_counter()

    # Sin product_id como etiqueta: evita alta cardinalidad en Prometheus.
    inventory_requests.add(1)

    if product_id in _inventory_cache:
        with tracer.start_as_current_span(
            "inventory.cache.hit",
            attributes={
                "cache.type": "in-memory",
                "product.id": product_id,
            },
        ):
            cache_hits.add(1)
            logger.info("Cache hit", extra={"product_id": product_id})
            return _inventory_cache[product_id]

    with tracer.start_as_current_span(
        "inventory.db.fetch",
        kind=trace.SpanKind.CLIENT,
        attributes={
            "db.system": "postgresql",
            "db.operation": "SELECT",
            "db.name": "appdb",
            "product.id": product_id,
        },
    ) as span:
        conn = None
        cur = None

        try:
            conn = get_db_connection()
            cur = conn.cursor()

            # Simulación de latencia variable de DB usada por el laboratorio.
            time.sleep(random.uniform(0.01, 0.15))

            cur.execute(
                "SELECT product_id, available, warehouse, last_updated "
                "FROM inventory WHERE product_id = %s",
                (product_id,),
            )
            row = cur.fetchone()

            duration = time.perf_counter() - started_at
            inventory_query_duration.record(
                duration,
                {"operation": "SELECT"},
            )

            if not row:
                span.set_status(trace.StatusCode.ERROR, "Product not found")
                raise HTTPException(
                    status_code=404,
                    detail=f"Product {product_id} not found",
                )

            result = {
                "product_id": row[0],
                "available": row[1],
                "warehouse": row[2],
                "last_updated": str(row[3]),
            }

            span.set_attribute("inventory.available", result["available"])
            span.set_attribute("inventory.warehouse", result["warehouse"])
            span.set_status(trace.StatusCode.OK)

            _inventory_cache[product_id] = result

            logger.info(
                "Inventory fetched from DB",
                extra={
                    "product_id": product_id,
                    "available": result["available"],
                    "duration_s": round(duration, 4),
                },
            )
            return result

        except HTTPException:
            raise
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            logger.error(
                "Inventory DB query failed",
                extra={"error": str(exc), "product_id": product_id},
            )
            raise HTTPException(
                status_code=500,
                detail="Inventory service error",
            ) from exc
        finally:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()


@app.post("/inventory/{product_id}/reserve")
async def reserve_inventory(product_id: str, quantity: int = 1):
    """Custom span de lógica de negocio para reservar inventario."""

    with tracer.start_as_current_span(
        "inventory.business.reserve",
        attributes={
            "product.id": product_id,
            "reservation.units": quantity,
        },
    ) as span:
        logger.info(
            "Reserving inventory",
            extra={"product_id": product_id, "quantity": quantity},
        )

        with tracer.start_as_current_span("inventory.validate.stock") as val_span:
            time.sleep(random.uniform(0.005, 0.02))
            available = random.randint(0, 100)
            val_span.set_attribute("stock.available", available)

            if available < quantity:
                val_span.set_status(trace.StatusCode.ERROR, "Insufficient stock")
                span.set_status(trace.StatusCode.ERROR, "Reservation failed")
                raise HTTPException(status_code=409, detail="Insufficient stock")

        span.set_attribute("reservation.approved", True)
        span.set_status(trace.StatusCode.OK)

        _inventory_cache.pop(product_id, None)

        return {
            "reserved": quantity,
            "product_id": product_id,
            "status": "confirmed",
        }


@app.get("/metrics/health")
async def metrics_health():
    return {
        "otel_enabled": OTEL_ENABLED,
        "otel_collector": OTEL_ENDPOINT if OTEL_ENABLED else None,
        "prometheus_port": PROMETHEUS_PORT if OTEL_ENABLED else None,
    }
