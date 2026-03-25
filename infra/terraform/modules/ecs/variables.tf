variable "name_prefix" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "service_name" {
  type = string
}

variable "task_family" {
  type = string
}

variable "secondary_enabled" {
  type    = bool
  default = false
}

variable "secondary_service_name" {
  type    = string
  default = ""
}

variable "secondary_desired_count" {
  type    = number
  default = 1
}

variable "container_name" {
  type = string
}

variable "container_image" {
  type = string
}

variable "container_port" {
  type = number
}

variable "cpu" {
  type = number
}

variable "memory" {
  type = number
}

variable "desired_count" {
  type = number
}

variable "subnet_ids" {
  type = list(string)
}

variable "security_group_ids" {
  type = list(string)
}

variable "assign_public_ip" {
  type = bool
}

variable "execution_role_arn" {
  type = string
}

variable "task_role_arn" {
  type = string
}

variable "secret_arn" {
  type = string
}

variable "cache_bucket_name" {
  type = string
}

variable "region" {
  type = string
}

variable "target_group_arn" {
  type = string
  default = null
}

variable "log_retention_in_days" {
  type = number
}
