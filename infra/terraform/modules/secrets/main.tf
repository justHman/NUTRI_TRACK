resource "aws_secretsmanager_secret" "api_keys" {
  name = var.secret_name
}

resource "aws_secretsmanager_secret_version" "api_keys" {
  secret_id = aws_secretsmanager_secret.api_keys.id

  secret_string = jsonencode({
    USDA_API_KEY               = var.usda_api_key
    AVOCAVO_NUTRITION_API_KEY  = var.avocavo_api_key
  })
}
