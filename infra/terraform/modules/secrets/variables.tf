variable "secret_name" {
  type = string
}

variable "usda_api_key" {
  type      = string
  sensitive = true
}

variable "avocavo_api_key" {
  type      = string
  sensitive = true
  default   = ""
}
