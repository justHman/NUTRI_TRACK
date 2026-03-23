variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "container_port" {
  type = number
}

variable "enable_alb_chain" {
  type    = bool
  default = true
}
