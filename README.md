# Laboratorio de Observabilidad End-to-End con OpenTelemetry sobre AWS

## Descripción

Este repositorio implementa un laboratorio completo de **observabilidad distribuida** para una aplicación basada en microservicios, con el propósito de capturar, procesar, visualizar y correlacionar **métricas, trazas y logs** utilizando **OpenTelemetry** como estándar transversal.

La solución está compuesta por `service-a`, `service-b` y PostgreSQL. Ambos servicios están instrumentados con **OpenTelemetry SDK para Python** y envían telemetría al **AWS Distro for OpenTelemetry Collector (ADOT)**. En el despliegue AWS, las métricas son enviadas a **Amazon Managed Service for Prometheus (AMP)**, las trazas a **AWS X-Ray** y los logs a **Amazon CloudWatch Logs**. La visualización se centraliza en **Grafana**, mientras que **k6** se utiliza para generar carga y analizar el overhead introducido por la instrumentación.

---

## Objetivos del laboratorio

El laboratorio busca demostrar una implementación práctica de observabilidad end-to-end, cubriendo los siguientes objetivos:

- Instrumentar aplicaciones Python con **OpenTelemetry SDK**.
- Implementar instrumentación automática y manual sobre FastAPI, HTTPX y PostgreSQL.
- Propagar contexto distribuido entre `service-a` y `service-b`.
- Centralizar la recepción y procesamiento de telemetría mediante **ADOT Collector**.
- Exportar métricas, trazas y logs hacia servicios administrados de AWS.
- Construir indicadores operativos y SLIs en Grafana.
- Correlacionar logs y trazas utilizando `trace_id` y `span_id`.
- Desplegar la solución sobre **Amazon ECS Fargate**.
- Gestionar infraestructura mediante **Terraform**.
- Comparar el comportamiento de la aplicación con y sin instrumentación mediante **k6**.

---

# Arquitectura de la solución

La arquitectura implementada desacopla la generación de telemetría de los backends de observabilidad. Las aplicaciones generan información bajo el estándar OpenTelemetry y el Collector se encarga de aplicar procesamiento, enriquecimiento, filtrado y exportación hacia los servicios de destino.

<img width="2107" height="1535" alt="Arquitectura-completa-obs" src="https://github.com/user-attachments/assets/67020770-58ca-4358-b5c3-1c3b2782075c" />


### Flujo principal

```text
Cliente / k6
     |
     v
Application Load Balancer
     |
     v
 service-a
     |
     | HTTP + W3C TraceContext
     v
 service-b
     |
     | SQL / psycopg2
     v
 PostgreSQL

service-a --------\
                   \
service-b ----------> ADOT Collector
                     /      |       \
                    /       |        \
                   v        v         v
                  AMP    AWS X-Ray   CloudWatch Logs
                   |                   |
                   +------- Grafana ---+

Amazon ECS --------> CloudWatch Metrics --------> Grafana
```

---

# Componentes tecnológicos

| Componente | Tecnología | Función |
|---|---|---|
| `service-a` | Python / FastAPI | Servicio principal y orquestador de solicitudes |
| `service-b` | Python / FastAPI | Servicio de inventario |
| Persistencia | PostgreSQL | Almacena órdenes e inventario |
| Instrumentación | OpenTelemetry SDK | Genera métricas, trazas y logs |
| Propagación | W3C TraceContext | Mantiene el contexto entre servicios |
| Collector | AWS Distro for OpenTelemetry | Recibe, procesa y exporta telemetría |
| Métricas | Amazon Managed Service for Prometheus | Backend administrado de métricas |
| Trazas | AWS X-Ray | Backend de trazabilidad distribuida |
| Logs | Amazon CloudWatch Logs | Centralización de logs |
| Infraestructura | Amazon ECS Fargate | Ejecución administrada de contenedores |
| Registro | Amazon ECR | Almacenamiento de imágenes Docker |
| Entrada | Application Load Balancer | Acceso HTTP a `service-a` |
| Visualización | Grafana | Dashboards y análisis de telemetría |
| IaC | Terraform | Definición declarativa de infraestructura |
| Contenedores | Docker / Docker Compose | Construcción y ejecución local |
| Carga | k6 | Pruebas de carga y benchmark |
| Seguridad | AWS IAM | Permisos para ECS, AMP, X-Ray y CloudWatch |
| Control de versiones | Git / GitHub | Versionamiento del laboratorio |

---

# Aplicación

## `service-a`

`service-a` actúa como punto de entrada de la aplicación. Expone endpoints HTTP mediante FastAPI, consulta la base de datos PostgreSQL y realiza llamadas hacia `service-b`.

Ruta principal:

```text
GET /order/{order_id}
```

El servicio implementa:

- Instrumentación FastAPI.
- Instrumentación HTTPX.
- Instrumentación Psycopg2.
- Spans manuales para operaciones relevantes.
- Métricas HTTP.
- Métricas de consultas a base de datos.
- Métricas de llamadas hacia `service-b`.
- Logs JSON correlacionados mediante `trace_id` y `span_id`.
- Activación o desactivación de OpenTelemetry mediante `OTEL_ENABLED`.

Archivo principal:

```text
service-a/main.py
```

---

## `service-b`

`service-b` representa el servicio de inventario y recibe solicitudes provenientes de `service-a`.

Endpoints principales:

```text
GET  /inventory/{product_id}
POST /inventory/{product_id}/reserve
```

La instrumentación mantiene el contexto distribuido recibido desde `service-a`, permitiendo visualizar una misma transacción a través de los diferentes componentes.

Archivo principal:

```text
service-b/main.py
```

---

# Instrumentación OpenTelemetry

Los dos microservicios utilizan **OpenTelemetry SDK 1.24.0** y sus instrumentadores asociados.

Las principales capacidades implementadas son:

```text
FastAPIInstrumentor
HTTPXClientInstrumentor
Psycopg2Instrumentor
OTLPSpanExporter
OTLPLogExporter
PrometheusMetricReader
AwsXRayIdGenerator
```

El uso de `AwsXRayIdGenerator` permite generar identificadores de trazas compatibles con AWS X-Ray.

La instrumentación se controla mediante:

```bash
OTEL_ENABLED=true
```

Para ejecutar el escenario baseline:

```bash
OTEL_ENABLED=false
```

Este mecanismo permite comparar el comportamiento de la aplicación con y sin instrumentación sin modificar la lógica funcional.

---

# Métricas implementadas

Los servicios exponen métricas de aplicación a través de Prometheus.

Entre las métricas definidas se encuentran:

```text
http_requests_total
http_request_duration_seconds
http_active_requests
db_query_duration_seconds
service_b_calls_total
```

Puertos utilizados:

| Servicio | Aplicación | Métricas |
|---|---:|---:|
| `service-a` | 8000 | 9090 |
| `service-b` | 8001 | 9091 |
| ADOT Collector | 4317 / 4318 | 8888 / 8889 |
| PostgreSQL | 5432 | — |

---

# Configuración del ADOT Collector

La configuración principal para AWS se encuentra en:

```text
otel-collector/collector-config-aws.yaml
```

El Collector implementa tres pipelines independientes.

## Pipeline de trazas

```text
OpenTelemetry SDK
      |
      v
OTLP Receiver
      |
      v
memory_limiter
resource
resourcedetection
filter/health
batch
      |
      v
AWS X-Ray
```

Los health checks son excluidos para reducir ruido en las trazas.

## Pipeline de métricas

```text
service-a :9090
service-b :9091
collector :8888
       |
       v
Prometheus Receiver
       |
       v
Processors
       |
       v
Prometheus Remote Write
       |
       | AWS SigV4
       v
Amazon Managed Service for Prometheus
```

## Pipeline de logs

```text
Aplicaciones
     |
     v
OTLP Receiver
     |
     v
Processors
     |
     v
Amazon CloudWatch Logs
```

Los processors configurados incluyen:

- `memory_limiter`
- `resource`
- `resourcedetection`
- `filter/health`
- `attributes/metrics`
- `batch`

---

# Despliegue sobre AWS

La implementación AWS utiliza una **ECS Task con modo de red `awsvpc`**, ejecutada sobre AWS Fargate.

La Task Definition principal se encuentra en:

```text
k8s/aws/ecs-task-definition-lab.json
```

La Task ejecuta cuatro contenedores:

```text
otel-collector
postgres
service-b
service-a
```

Configuración registrada en la definición actual:

```text
CPU Task:    2048
Memoria:     4096 MiB
NetworkMode: awsvpc
```

Debido a que los cuatro contenedores se ejecutan dentro de la misma ECS Task, pueden comunicarse mediante la interfaz loopback:

```text
service-a -> service-b
http://127.0.0.1:8001

service-a / service-b -> ADOT
http://127.0.0.1:4317

service-a / service-b -> PostgreSQL
127.0.0.1:5432
```

El Application Load Balancer publica únicamente `service-a`.

---

# Dependencias y health checks

El orden de arranque está controlado desde la Task Definition:

```text
PostgreSQL
    |
    +---- HEALTHY ----> service-b
                           |
                           +---- HEALTHY ----> service-a

ADOT Collector
    |
    +---- START ------> service-a / service-b
```

Health checks implementados:

```text
service-a: http://127.0.0.1:8000/health
service-b: http://127.0.0.1:8001/health
postgres:  pg_isready
```

---

# Persistencia

El script de inicialización se encuentra en:

```text
scripts/init-db.sql
```

Se crean las tablas:

```text
orders
inventory
```

El laboratorio incorpora datos iniciales de prueba, entre ellos:

```text
ord-001
ord-002
ord-003
ord-004
ord-005
```

Ejemplo de consulta funcional:

```bash
GET /order/ord-002
```

La respuesta permite validar la consulta de la orden, el inventario asociado y, cuando OpenTelemetry está habilitado, el `trace_id` generado para la transacción.

---

# Trazabilidad distribuida

## Backend AWS: X-Ray

En el despliegue AWS, **AWS X-Ray reemplaza a Jaeger como backend principal de trazas**.

El flujo es:

```text
service-a
    |
    | W3C TraceContext
    v
service-b
    |
    v
PostgreSQL

    |
    v
ADOT Collector
    |
    v
AWS X-Ray
```

Las trazas pueden consultarse desde AWS X-Ray y mediante AWS CLI.

Ejemplo:

```powershell
$END = (Get-Date).ToUniversalTime()
$START = $END.AddMinutes(-15)

aws xray get-trace-summaries `
    --start-time $START.ToString("yyyy-MM-ddTHH:mm:ssZ") `
    --end-time $END.ToString("yyyy-MM-ddTHH:mm:ssZ") `
    --region us-east-1 `
    --query "TraceSummaries[].{TraceId:Id,Duration:Duration,HttpStatus:Http.HttpStatus}" `
    --output table
```

El repositorio conserva además una configuración local con **Jaeger y Tempo** dentro de `docker-compose.yaml`. Estos componentes son útiles para desarrollo local, mientras que la arquitectura AWS documentada utiliza X-Ray como backend final.

---

# Logs y correlación

Los servicios generan logs estructurados JSON incluyendo metadatos de contexto:

```text
service
version
environment
trace_id
span_id
```

Esto permite correlacionar un evento registrado en CloudWatch con la traza distribuida asociada.

Los logs de aplicación se gestionan en CloudWatch y el Collector utiliza adicionalmente el exporter:

```text
awscloudwatchlogs
```

---

# Métricas y Grafana

Grafana consolida la visualización de los principales indicadores del laboratorio.

El dashboard versionado se encuentra en:

```text
grafana/dashboards/otel-lab-dashboard.json
```

El dashboard incluye los siguientes indicadores:

| Panel | Objetivo |
|---|---|
| Disponibilidad | Porcentaje de solicitudes exitosas |
| Latencia p50 / p95 / p99 | Comportamiento de tiempos de respuesta |
| Error Rate 5xx | Porcentaje de errores del servidor |
| Throughput / RPS | Solicitudes procesadas por segundo |
| CPU Overhead | Impacto de la instrumentación en CPU |
| OTel Collector | Spans enviados, rechazados y en cola |
| Burn Rate | Velocidad de consumo del Error Budget |
| Propagación W3C | Validación de tráfico cross-service |

Grafana puede operar en dos modalidades.

### Stack local

El archivo:

```text
docker-compose.yaml
```

incluye:

```text
Grafana
Prometheus
Jaeger
Tempo
ADOT Collector
PostgreSQL
service-a
service-b
```

### Grafana local consultando AWS

El archivo:

```text
docker-compose.grafana-aws.yaml
```

permite ejecutar Grafana local con plugins para:

```text
Amazon Managed Service for Prometheus
AWS X-Ray
```

El acceso se realiza en:

```text
http://localhost:3000
```

---

# Evidencias del laboratorio

Las evidencias gráficas se encuentran en:

```text
EVIDENCIAS IMAGENES/
```

## AWS CloudWatch

La siguiente evidencia muestra métricas y registros disponibles en CloudWatch:

![CloudWatch](EVIDENCIAS%20IMAGENES/Evidencia1.png)

## Amazon ECS Fargate

Estado del servicio ECS y métricas de CPU y memoria:

![Amazon ECS](EVIDENCIAS%20IMAGENES/Evidencia2.png)

## Generación de tráfico

Ejecución de solicitudes sobre el Application Load Balancer:

![Generación de tráfico](EVIDENCIAS%20IMAGENES/Evidencia3.png)

## Transacción end-to-end y Trace ID

Respuesta funcional de `/order/ord-002` incluyendo información de orden, inventario y `trace_id`:

![Transacción end-to-end](EVIDENCIAS%20IMAGENES/Evidencia4.png)

## Trazas en AWS X-Ray

Consulta de trazas distribuidas mediante AWS CLI:

![AWS X-Ray](EVIDENCIAS%20IMAGENES/Evidencia5.png)

---

# Evidencias Grafana

## Catálogo de dashboards

![Dashboards Grafana](EVIDENCIAS%20IMAGENES/Evidencia6_dashboardGrafana.png)

## Exploración de métricas

![Todas las métricas](EVIDENCIAS%20IMAGENES/Evidencia7_Grafana1.png)

![Métricas Grafana](EVIDENCIAS%20IMAGENES/Evidencia8_Grafana2.png)

## Latencia p95

![Latencia p95](EVIDENCIAS%20IMAGENES/Evidencia9_Grafana3.png)

## Disponibilidad

![Disponibilidad](EVIDENCIAS%20IMAGENES/Evidencia10_Grafana4.png)

## Errores del OTel Collector

![Errores OTel Collector](EVIDENCIAS%20IMAGENES/Evidencia11_Grafana5.png)

## CPU ECS Fargate

![CPU ECS](EVIDENCIAS%20IMAGENES/Evidencia12_Grafana6.png)

## Throughput / RPS

![Throughput](EVIDENCIAS%20IMAGENES/Evidencia13_Grafana7.png)

---

# Infrastructure as Code

Los manifiestos Terraform se encuentran en:

```text
iac/terraform/
```

Estructura:

```text
versions.tf
variables.tf
iam.tf
network.tf
observability.tf
ecs.tf
outputs.tf
terraform.tfvars.example
```

Los manifiestos modelan:

- ECS Cluster.
- ECS Task Definition.
- ECS Service.
- Application Load Balancer.
- Target Group.
- Security Groups.
- IAM Execution Role.
- IAM Task Role.
- Permisos de AMP Remote Write.
- Permisos de AWS X-Ray.
- Permisos de CloudWatch.
- CloudWatch Log Groups.

Ejecución:

```bash
cd iac/terraform

terraform init
terraform fmt
terraform validate
terraform plan
```

Antes de un `terraform apply` deben reemplazarse los valores de ejemplo contenidos en:

```text
terraform.tfvars.example
```

---

# Nota de consistencia sobre secretos

El repositorio contiene dos aproximaciones de gestión de secretos que deben unificarse antes de utilizar Terraform como mecanismo definitivo de despliegue:

- La **Task Definition ECS actual** referencia parámetros almacenados en **AWS Systems Manager Parameter Store** para `DATABASE_URL` y la contraseña de PostgreSQL.
- Los **manifiestos Terraform** incluidos modelan la contraseña mediante un ARN de secreto y permisos de **AWS Secrets Manager**.

Ambas alternativas son válidas, pero para un despliegue productivo se recomienda seleccionar un único mecanismo y mantenerlo consistente en IaC, Task Definition y arquitectura.

---

# Benchmark y análisis de overhead

El laboratorio incorpora un benchmark con k6 para medir el impacto de OpenTelemetry.

Archivos:

```text
benchmark/k6_benchmark.js
benchmark/analyze_overhead.py
```

Se comparan dos escenarios:

```text
Baseline:
OTEL_ENABLED=false

Instrumentado:
OTEL_ENABLED=true
```

La prueba evalúa principalmente:

- Latencia promedio.
- Latencia p95.
- Latencia p99.
- Tasa de errores.
- Throughput.
- CPU.
- Memoria.

Ejemplo de ejecución:

```bash
k6 run --env INSTRUMENTED=false benchmark/k6_benchmark.js
```

Posteriormente:

```bash
k6 run --env INSTRUMENTED=true benchmark/k6_benchmark.js
```

El análisis comparativo puede realizarse con:

```bash
python benchmark/analyze_overhead.py
```

La fórmula utilizada para calcular el overhead relativo es:

```text
Overhead (%) =
((Valor con OTel - Valor baseline) / Valor baseline) × 100
```

El repositorio contiene los scripts para ejecutar y analizar la comparación; no se identificaron archivos `results_baseline.json` o `results_otel.json` dentro del ZIP analizado, por lo que los valores finales deben generarse ejecutando el benchmark en el ambiente objetivo.

---

# Decisiones de diseño

La arquitectura fue diseñada para mantener una separación clara entre la **instrumentación de la aplicación** y los **backends de observabilidad**. OpenTelemetry funciona como capa estándar y ADOT Collector como punto de control central, permitiendo cambiar o complementar destinos de métricas, trazas y logs sin modificar la lógica funcional de los microservicios.

Se eligió **Amazon ECS Fargate** para reducir la administración de infraestructura y ejecutar los componentes de manera contenida. La combinación de AMP, X-Ray, CloudWatch y Grafana permite cubrir las tres señales principales de observabilidad, mientras que Terraform, Docker y Git aportan reproducibilidad y control de cambios.

---

# Ejecución local

## Requisitos

- Docker Desktop
- Docker Compose
- Git
- Python 3
- k6, si se ejecutará el benchmark

Levantar el stack:

```bash
docker compose up -d
```

Verificar:

```bash
docker compose ps
```

Servicios locales principales:

```text
service-a:       http://localhost:8000
service-b:       http://localhost:8001
Grafana:         http://localhost:3000
Jaeger UI:       http://localhost:16686
Prometheus UI:   http://localhost:9091
Collector OTLP:  localhost:4317 / 4318
```

Prueba funcional:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/order/ord-002
```

Finalizar:

```bash
docker compose down -v
```

---

# Validación en AWS

Una validación mínima del laboratorio debe confirmar:

```text
ECS Service        -> RUNNING
Target Group       -> healthy
service-a /health  -> HTTP 200
/order/ord-002     -> HTTP 200 + trace_id
AMP                -> métricas disponibles
AWS X-Ray          -> trazas distribuidas
CloudWatch Logs    -> logs con trace_id
Grafana            -> dashboards consultando métricas
```

Consulta de estado ECS:

```bash
aws ecs describe-services \
  --cluster otel-lab \
  --services otel-lab-svc \
  --region us-east-1
```

---

# Seguridad

La configuración del laboratorio incorpora roles IAM independientes para ejecución y operación de la Task.

Permisos principales:

```text
AmazonPrometheusRemoteWriteAccess
AWSXRayDaemonWriteAccess
CloudWatchAgentServerPolicy
```

Los secretos no deben almacenarse directamente dentro del código fuente ni en archivos versionados.

> **Importante:** el ZIP analizado contiene localmente el archivo `.grafana-aws.env`, que incluye variables de credenciales AWS. El `.gitignore` del repositorio lo excluye de Git y debe mantenerse así. Este archivo no debe subirse al repositorio ni distribuirse. Si alguna credencial asociada fue publicada previamente, debe rotarse.

También deben mantenerse fuera de Git:

```text
terraform.tfvars
*.tfstate
.grafana-aws.env
.grafana-aws/
```

---

# Estructura del repositorio

```text
oTelLabs_Usabana/
│
├── aws/
│   ├── collector/
│   ├── iam/
│   └── postgres/
│
├── benchmark/
│   ├── analyze_overhead.py
│   └── k6_benchmark.js
│
├── Diagramas/
│   └── Arquitectura-completa-obs.png
│
├── Documento Tecnico/
│   └── Documento técnico Entregable.pdf
│
├── EVIDENCIAS IMAGENES/
│   ├── Evidencia1.png
│   ├── ...
│   └── Evidencia13_Grafana7.png
│
├── grafana/
│   ├── dashboards/
│   └── provisioning/
│
├── iac/
│   └── terraform/
│
├── k8s/
│   ├── aws/
│   └── gcp/
│
├── otel-collector/
│   ├── collector-config.yaml
│   ├── collector-config-aws.yaml
│   └── Dockerfile.aws
│
├── prometheus/
│   └── prometheus.yaml
│
├── scripts/
│   └── init-db.sql
│
├── service-a/
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
│
├── service-b/
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
│
├── tempo/
│   └── tempo.yaml
│
├── docker-compose.yaml
├── docker-compose.grafana-aws.yaml
└── .gitignore
```

---

# Documento técnico

El repositorio incluye el documento técnico del entregable dentro de:

```text
Documento Tecnico/
```

Este documento consolida la descripción ejecutiva del laboratorio, instrumentación, Collector, IaC, trazabilidad, dashboards, arquitectura, decisiones de diseño y análisis de overhead.

---

# Resultado

El laboratorio implementa un pipeline de observabilidad completo y desacoplado:

```text
Aplicación
   |
OpenTelemetry SDK
   |
OTLP / Prometheus
   |
ADOT Collector
   |
   +------ Métricas -----> AMP --------> Grafana
   |
   +------ Trazas -------> AWS X-Ray
   |
   +------ Logs ---------> CloudWatch Logs
```

La solución demuestra que es posible instrumentar una arquitectura de microservicios utilizando un estándar abierto, operar la recolección de telemetría mediante un Collector centralizado y consumir servicios administrados de AWS sin acoplar la lógica de negocio a un proveedor específico.

---

## Autor

**Giovani Esteban Romero**  
Maestría en Arquitectura de Software  
Universidad de La Sabana

---

## Repositorio

Laboratorio académico de observabilidad con OpenTelemetry, AWS, Grafana, Prometheus, Docker, Terraform y k6.
