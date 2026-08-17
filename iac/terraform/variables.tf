variable "aws_region" {
  description = "Región AWS utilizada por el laboratorio."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Ambiente de ejecución."
  type        = string
  default     = "aws-lab"
}

variable "cluster_name" {
  description = "Nombre del cluster ECS."
  type        = string
  default     = "otel-lab"
}

variable "service_name" {
  description = "Nombre del servicio ECS."
  type        = string
  default     = "otel-lab-svc"
}

variable "task_family" {
  description = "Familia de la Task Definition."
  type        = string
  default     = "otel-lab"
}

variable "vpc_id" {
  description = "VPC utilizada por el laboratorio."
  type        = string
}

variable "public_subnet_ids" {
  description = "Subnets públicas del ALB."
  type        = list(string)
}

variable "ecs_subnet_ids" {
  description = "Subnets usadas por ECS Fargate."
  type        = list(string)
}

variable "assign_public_ip" {
  description = "Asigna IP pública a la tarea Fargate."
  type        = bool
  default     = true
}

variable "service_a_image" {
  description = "Imagen ECR de service-a."
  type        = string
}

variable "service_b_image" {
  description = "Imagen ECR de service-b."
  type        = string
}

variable "collector_image" {
  description = "Imagen ECR del ADOT Collector."
  type        = string
}

variable "postgres_image" {
  description = "Imagen PostgreSQL."
  type        = string
  default     = "postgres:16"
}

variable "postgres_user" {
  description = "Usuario PostgreSQL."
  type        = string
  default     = "otel"
}

variable "postgres_database" {
  description = "Base de datos PostgreSQL."
  type        = string
  default     = "otel"
}

variable "postgres_password_secret_arn" {
  description = "ARN del secreto de PostgreSQL en AWS Secrets Manager."
  type        = string
  sensitive   = true
}

variable "task_cpu" {
  type    = string
  default = "1024"
}

variable "task_memory" {
  type    = string
  default = "2048"
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "ecs_log_retention_days" {
  type    = number
  default = 14
}

variable "application_log_retention_days" {
  type    = number
  default = 14
}
