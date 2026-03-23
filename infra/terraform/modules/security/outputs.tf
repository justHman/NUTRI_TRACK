output "public_task_sg_id" {
  value = aws_security_group.public_task.id
}

output "alb_sg_id" {
  value = try(aws_security_group.alb[0].id, null)
}

output "private_task_sg_id" {
  value = try(aws_security_group.private_task[0].id, null)
}
