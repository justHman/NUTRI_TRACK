output "alb_dns_name" {
  value = var.enabled ? aws_lb.this[0].dns_name : null
}

output "target_group_arn" {
  value = var.enabled ? aws_lb_target_group.this[0].arn : null
}
