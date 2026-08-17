resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/otel-lab"
  retention_in_days = var.ecs_log_retention_days
}

resource "aws_cloudwatch_log_group" "application" {
  name              = "/otel-lab/application"
  retention_in_days = var.application_log_retention_days
}
