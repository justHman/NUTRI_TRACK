variable "aws_region" {
  type    = string
  default = "ap-southeast-2"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "owner" {
  type    = string
  default = "ai_02"
}

variable "vpc_name" {
  type    = string
  default = "nutritrack-api-vpc"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "ecr_repository_name" {
  type    = string
  default = "backend/nutritrack-api-image"
}

variable "s3_cache_bucket" {
  type    = string
  default = "nutritrack-cache-01apr26"
}

variable "ecs_cluster_name" {
  type    = string
  default = "nutritrack-api-cluster"
}

variable "ecs_service_name" {
  type    = string
  default = "spot-arm-nutritrack-api-task-service"
}

variable "task_family" {
  type    = string
  default = "arm-nutritrack-api-task"
}

variable "container_name" {
  type    = string
  default = "arm-nutritrack-api-container"
}

variable "container_port" {
  type    = number
  default = 8000
}
