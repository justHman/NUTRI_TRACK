resource "random_string" "suffix" {
  length  = 6
  upper   = false
  lower   = true
  numeric = true
  special = false
}

locals {
  final_bucket_name = coalesce(var.bucket_name, "${var.name_prefix}-cache-${random_string.suffix.result}")
}

resource "aws_s3_bucket" "cache" {
  bucket = local.final_bucket_name
}

resource "aws_s3_bucket_public_access_block" "cache" {
  bucket = aws_s3_bucket.cache.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
