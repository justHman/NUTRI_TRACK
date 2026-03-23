output "bucket_name" {
  value = aws_s3_bucket.cache.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.cache.arn
}
