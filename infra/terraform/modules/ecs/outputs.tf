output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "secondary_service_name" {
  value = try(aws_ecs_service.secondary[0].name, null)
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.this.arn
}
