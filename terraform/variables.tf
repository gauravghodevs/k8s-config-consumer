variable "aws_region" {
  description = "AWS region for Blast-Radius Guard infrastructure"
  type        = string
  default     = "ap-south-1"
}

variable "bucket_name" {
  description = "Existing S3 bucket used for versioned configuration artifacts"
  type        = string
}

variable "noncurrent_version_expiration_days" {
  description = "Number of days before noncurrent S3 object versions expire"
  type        = number
  default     = 30
}
