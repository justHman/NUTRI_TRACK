variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name prefix"
  type        = string
  default     = "nutritrack"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "deployment_mode" {
  description = "Deployment mode: public or private_alb"
  type        = string
  default     = "private_alb"

  validation {
    condition     = contains(["public", "private_alb"], var.deployment_mode)
    error_message = "deployment_mode must be either 'public' or 'private_alb'."
  }
}

variable "vpc_cidr" {
  description = "VPC CIDR"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "Public subnet CIDR"
  type        = string
  default     = "10.0.1.0/24"
}

variable "private_subnet_cidr" {
  description = "Private subnet CIDR"
  type        = string
  default     = "10.0.2.0/24"
}

variable "container_port" {
  description = "Container port"
  type        = number
  default     = 8000
}

variable "container_cpu" {
  description = "Fargate task CPU"
  type        = number
  default     = 1024
}

variable "container_memory" {
  description = "Fargate task memory"
  type        = number
  default     = 2048
}

variable "desired_count" {
  description = "Desired ECS task count"
  type        = number
  default     = 1
}

variable "log_retention_in_days" {
  description = "CloudWatch log retention for ECS logs"
  type        = number
  default     = 14
}

variable "container_image" {
  description = "Container image URI"
  type        = string
  default     = "docker.io/library/nginx:latest"
}

variable "container_name" {
  description = "Container name in task definition"
  type        = string
  default     = "nutritrack-api-container"
}

variable "s3_bucket_name" {
  description = "Optional fixed S3 bucket name for cache; if null, name is generated"
  type        = string
  default     = null
}

variable "secrets_name" {
  description = "Secrets Manager secret name"
  type        = string
  default     = "nutritrack/prod/api-keys"
}

variable "usda_api_key" {
  description = "USDA API key"
  type        = string
  sensitive   = true
}

variable "avocavo_api_key" {
  description = "Optional Avocavo Nutrition API key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "tags" {
  description = "Extra tags"
  type        = map(string)
  default     = {}
}
