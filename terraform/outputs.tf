output "bucket_name" {
  description = "S3 configuration bucket name"
  value       = aws_s3_bucket.config.bucket
}

output "bucket_arn" {
  description = "S3 configuration bucket ARN"
  value       = aws_s3_bucket.config.arn
}

output "bucket_region" {
  description = "AWS region containing the configuration bucket"
  value       = var.aws_region
}

output "controller_s3_policy_arn" {
  description = "ARN of the least-privilege S3 policy for the controller"
  value       = aws_iam_policy.controller_s3.arn
}
