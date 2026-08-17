output "ecs_cluster_name" {
  value = aws_ecs_cluster.otel_lab.name
}

output "ecs_service_name" {
  value = aws_ecs_service.otel_lab.name
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.otel_lab.arn
}

output "alb_dns_name" {
  value = aws_lb.otel_lab.dns_name
}

output "task_role_arn" {
  value = aws_iam_role.ecs_task_role.arn
}

output "execution_role_arn" {
  value = aws_iam_role.ecs_execution_role.arn
}

output "ecs_log_group" {
  value = aws_cloudwatch_log_group.ecs.name
}

output "application_log_group" {
  value = aws_cloudwatch_log_group.application.name
}
