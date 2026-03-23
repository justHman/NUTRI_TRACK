output "secret_arn" {
  value = aws_secretsmanager_secret.api_keys.arn
}

output "secret_name" {
  value = aws_secretsmanager_secret.api_keys.name
}
