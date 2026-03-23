locals {
  name_prefix = "${var.project_name}-${var.environment}"

  use_private_alb_mode = var.deployment_mode == "private_alb"

  common_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    },
    var.tags,
  )
}
