variable "enabled" {
  type = bool
}

variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "security_group_id" {
  type = string
}

variable "health_check_path" {
  type = string
}

variable "container_port" {
  type = number
}
