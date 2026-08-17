resource "aws_ecs_cluster" "otel_lab" {
  name = var.cluster_name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "otel_lab" {
  family                   = var.task_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "postgres"
      image     = var.postgres_image
      essential = true
      portMappings = [{
        containerPort = 5432
        hostPort      = 5432
        protocol      = "tcp"
      }]
      environment = [
        { name = "POSTGRES_USER", value = var.postgres_user },
        { name = "POSTGRES_DB", value = var.postgres_database }
      ]
      secrets = [{
        name      = "POSTGRES_PASSWORD"
        valueFrom = var.postgres_password_secret_arn
      }]
      healthCheck = {
        command     = ["CMD-SHELL", "pg_isready -U ${var.postgres_user} -d ${var.postgres_database} || exit 1"]
        interval    = 10
        timeout     = 5
        retries     = 5
        startPeriod = 30
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "postgres"
        }
      }
    },
    {
      name      = "otel-collector"
      image     = var.collector_image
      essential = true
      command   = ["--config=/etc/otel-config.yaml"]
      portMappings = [
        { containerPort = 4317, protocol = "tcp" },
        { containerPort = 4318, protocol = "tcp" },
        { containerPort = 8888, protocol = "tcp" },
        { containerPort = 8889, protocol = "tcp" },
        { containerPort = 13133, protocol = "tcp" }
      ]
      environment = [
        { name = "ENVIRONMENT", value = var.environment },
        { name = "CLOUD_REGION", value = var.aws_region }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "otel-collector"
        }
      }
    },
    {
      name      = "service-b"
      image     = var.service_b_image
      essential = true
      portMappings = [
        { containerPort = 8001, protocol = "tcp" },
        { containerPort = 9091, protocol = "tcp" }
      ]
      dependsOn = [
        { containerName = "postgres", condition = "HEALTHY" },
        { containerName = "otel-collector", condition = "START" }
      ]
      environment = [
        { name = "OTEL_ENABLED", value = "true" },
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://127.0.0.1:4317" },
        { name = "DB_HOST", value = "127.0.0.1" },
        { name = "DB_PORT", value = "5432" },
        { name = "DB_NAME", value = var.postgres_database },
        { name = "DB_USER", value = var.postgres_user }
      ]
      secrets = [{
        name      = "DB_PASSWORD"
        valueFrom = var.postgres_password_secret_arn
      }]
      healthCheck = {
        command = [
          "CMD-SHELL",
          "python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3); exit(0 if r.status == 200 else 1)" || exit 1"
        ]
        interval    = 10
        timeout     = 5
        retries     = 5
        startPeriod = 60
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "service-b"
        }
      }
    },
    {
      name      = "service-a"
      image     = var.service_a_image
      essential = true
      portMappings = [
        { containerPort = 8000, protocol = "tcp" },
        { containerPort = 9090, protocol = "tcp" }
      ]
      dependsOn = [
        { containerName = "service-b", condition = "HEALTHY" },
        { containerName = "otel-collector", condition = "START" }
      ]
      environment = [
        { name = "OTEL_ENABLED", value = "true" },
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://127.0.0.1:4317" },
        { name = "SERVICE_B_URL", value = "http://127.0.0.1:8001" }
      ]
      healthCheck = {
        command = [
          "CMD-SHELL",
          "python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3); exit(0 if r.status == 200 else 1)" || exit 1"
        ]
        interval    = 10
        timeout     = 5
        retries     = 5
        startPeriod = 60
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "service-a"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "otel_lab" {
  name            = var.service_name
  cluster         = aws_ecs_cluster.otel_lab.id
  task_definition = aws_ecs_task_definition.otel_lab.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  health_check_grace_period_seconds = 90

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = var.ecs_subnet_ids
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = var.assign_public_ip
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.service_a.arn
    container_name   = "service-a"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}
