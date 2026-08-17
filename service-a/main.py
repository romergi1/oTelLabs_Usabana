"""
service-a: FastAPI — Orquestador principal.

Recibe requests HTTP externos, consulta PostgreSQL y llama a service-b.
La instrumentación OpenTelemetry puede habilitarse/deshabilitarse con
OTEL_ENABLED para permitir un benchmark real de overhead.
"""

import logging
import os
import time
from contextlib import asynccontextmanager

import httpx
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
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.propagate import inject
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
SERVICE_B_URL = os.getenv("SERVICE_B_URL", "http://service-b:8001")
DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://app:secret@postgres:5432/appdb",
)
PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", "9090"))
ENV = os.getenv("ENVIRONMENT", "production")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")

# ── 5.5 Baseline real ────────────────────────────────────────────────────────
# true  -> OpenTelemetry habilitado
# false -> servicio funcional, pero sin providers/exporters/instrumentadores OTel
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "true").strip().lower() == "true"

resource = None
tracer_provider = None
meter_provider = None
logger_provider = None


# ── 5.1 / 5.2 / 5.4 / 5.5 Inicialización OpenTelemetry ──────────────────────
if OTEL_ENABLED:
    # Resource común para trazas, métricas y logs.
    resource = Resource.create(
        {
            SERVICE_NAME: "service-a",
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

    # Métricas: un solo camino de salida mediante Prometheus scraping.
    # El Collector hará scrape del puerto 9090 y enviará las métricas al backend.
    prometheus_reader = PrometheusMetricReader()
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[prometheus_reader],
    )
    metrics.set_meter_provider(meter_provider)

    # Auto-instrumentación que no depende del objeto FastAPI `app`.
    HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider)
    # Psycopg2Instrumentor().instrument(tracer_provider=tracer_provider)
    
    Psycopg2Instrumentor().instrument(
        tracer_provider=tracer_provider,
        skip_dep_check=True,
    )


# Las APIs de OTel retornan implementaciones no-op cuando no hay provider SDK.
# Esto permite mantener los spans/métricas manuales sin duplicar la lógica negocio.
tracer = trace.get_tracer("service-a", APP_VERSION)
meter = metrics.get_meter("service-a", APP_VERSION)


# ── 5.3 Instrumentos de métricas HTTP homogéneos ─────────────────────────────
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

# Métricas adicionales de service-a.
db_query_duration = meter.create_histogram(
    "db_query_duration_seconds",
    description="Latencia de consultas a PostgreSQL",
    unit="s",
)
service_b_calls_total = meter.create_counter(
    "service_b_calls_total",
    description="Llamadas HTTP realizadas a service-b",
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

        log_record["service"] = "service-a"
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

# Segundo destino únicamente cuando OTel está habilitado:
# logging -> OTLP -> Collector.
if OTEL_ENABLED and logger_provider is not None:
    otel_log_handler = LoggingHandler(
        level=logging.INFO,
        logger_provider=logger_provider,
    )
    otel_log_handler.setFormatter(json_formatter)
    root_logger.addHandler(otel_log_handler)

logger = logging.getLogger("service-a")


# ── Conexión DB ───────────────────────────────────────────────────────────────
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

    # Flush/shutdown solamente de providers que realmente fueron creados.
    if tracer_provider is not None:
        tracer_provider.shutdown()
    if meter_provider is not None:
        meter_provider.shutdown()
    if logger_provider is not None:
        logger_provider.shutdown()


# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Service A",
    description="Microservicio orquestador — OTel end-to-end lab",
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


# El middleware de métricas forma parte del overhead OTel y no debe ejecutarse
# en el baseline.
if OTEL_ENABLED:
    app.middleware("http")(record_http_slis)

    # La instrumentación FastAPI necesita que `app` ya exista.
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "service-a",
        "otel_enabled": OTEL_ENABLED,
    }


@app.get("/order/{order_id}")
async def get_order(order_id: str, request: Request):
    """
    Flujo principal:
    1. Consulta PostgreSQL para obtener el pedido.
    2. Llama a service-b para obtener inventario.
    3. Retorna la respuesta consolidada y, si OTel está activo, el trace_id.
    """

    # Custom span de lógica de negocio DB. En baseline es un span no-op.
    with tracer.start_as_current_span(
        "fetch.order.db",
        kind=trace.SpanKind.CLIENT,
        attributes={
            "db.system": "postgresql",
            "db.operation": "SELECT",
            "db.name": "appdb",
            "order.id": order_id,
        },
    ) as db_span:
        db_start = time.perf_counter()
        conn = None
        cur = None

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, product, quantity, status FROM orders WHERE id = %s",
                (order_id,),
            )
            row = cur.fetchone()

            db_duration = time.perf_counter() - db_start
            db_query_duration.record(
                db_duration,
                {"operation": "SELECT", "table": "orders"},
            )

            if not row:
                db_span.set_status(trace.StatusCode.ERROR, "Order not found")
                raise HTTPException(
                    status_code=404,
                    detail=f"Order {order_id} not found",
                )

            order_data = {
                "id": row[0],
                "product": row[1],
                "quantity": row[2],
                "status": row[3],
            }
            db_span.set_attribute("order.status", order_data["status"])

            logger.info(
                "Order fetched from DB",
                extra={
                    "order_id": order_id,
                    "status": order_data["status"],
                },
            )

        except HTTPException:
            raise
        except Exception as exc:
            db_span.record_exception(exc)
            db_span.set_status(trace.StatusCode.ERROR, str(exc))
            logger.error(
                "DB query failed",
                extra={"error": str(exc), "order_id": order_id},
            )
            raise HTTPException(status_code=500, detail="Database error") from exc
        finally:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()

    # Custom span de lógica de negocio alrededor de la llamada HTTP.
    # HTTPXClientInstrumentor crea adicionalmente el span de cliente HTTP real.
    with tracer.start_as_current_span(
        "call.service-b.inventory",
        kind=trace.SpanKind.CLIENT,
        attributes={
            "http.method": "GET",
            "peer.service": "service-b",
            "order.product": order_data["product"],
        },
    ) as service_b_span:
        service_b_calls_total.add(1, {"status": "attempt"})

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                headers = {}
                # Propagación W3C explícita como fallback. Con OTel desactivado,
                # el contexto es inválido y no se inyecta un traceparent útil.
                inject(headers)

                response = await client.get(
                    f"{SERVICE_B_URL}/inventory/{order_data['product']}",
                    headers=headers,
                )
                response.raise_for_status()
                inventory = response.json()

            service_b_calls_total.add(1, {"status": "success"})
            service_b_span.set_attribute("http.status_code", response.status_code)
            service_b_span.set_attribute(
                "inventory.available",
                inventory.get("available", 0),
            )

            logger.info(
                "Inventory fetched from service-b",
                extra={
                    "product": order_data["product"],
                    "available": inventory.get("available"),
                },
            )

        except httpx.HTTPError as exc:
            service_b_calls_total.add(1, {"status": "error"})
            service_b_span.record_exception(exc)
            service_b_span.set_status(trace.StatusCode.ERROR, str(exc))

            logger.error(
                "service-b call failed",
                extra={"error": str(exc)},
            )
            inventory = {
                "available": -1,
                "error": "service-b unavailable",
            }

    current_context = trace.get_current_span().get_span_context()
    trace_id = None
    if OTEL_ENABLED and current_context and current_context.is_valid:
        trace_id = format(current_context.trace_id, "032x")

    return {
        "order": order_data,
        "inventory": inventory,
        "trace_id": trace_id,
    }


@app.get("/metrics/health")
async def metrics_health():
    return {
        "otel_enabled": OTEL_ENABLED,
        "otel_collector": OTEL_ENDPOINT if OTEL_ENABLED else None,
        "prometheus_port": PROMETHEUS_PORT if OTEL_ENABLED else None,
        "service_b_url": SERVICE_B_URL,
    }
