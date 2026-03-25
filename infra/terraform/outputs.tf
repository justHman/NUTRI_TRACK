output "vpc_id" {
  description = "VPC id"
  value       = module.networking.vpc_id
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs.cluster_name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = module.ecs.service_name
}

output "ecs_service_arm_spot_name" {
  description = "Secondary ECS arm-spot service name when enabled"
  value       = module.ecs.secondary_service_name
}

output "cache_bucket_name" {
  description = "S3 cache bucket name"
  value       = module.storage.bucket_name
}

output "alb_dns_name" {
  description = "ALB DNS name when private_alb mode is enabled"
  value       = module.alb.alb_dns_name
}

output "service_health_url" {
  description = "Health endpoint URL"
  value       = local.use_private_alb_mode ? "http://${module.alb.alb_dns_name}/health" : null
}
