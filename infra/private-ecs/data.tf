resource "aws_s3_bucket" "cache" {
  bucket = var.s3_cache_bucket
  
  # Protect from accidental deletion
  lifecycle {
    prevent_destroy = false
  }
}

resource "aws_ecr_repository" "api_image" {
  name                 = var.ecr_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_secretsmanager_secret" "api_keys" {
  name = "nutritrack/prod/api-keys"
}
