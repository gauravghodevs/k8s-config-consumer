
resource "aws_ecr_repository" "consumer" {
  name                 = "blast-radius-consumer"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project = "blast-radius"
    Purpose = "config-consumer"
  }
}

resource "aws_ecr_repository" "validator" {
  name                 = "blast-radius-validator"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Project = "blast-radius"
    Purpose = "lambda-validator"
  }
}

output "consumer_ecr_repository_url" {
  value = aws_ecr_repository.consumer.repository_url
}

output "validator_ecr_repository_url" {
  value = aws_ecr_repository.validator.repository_url
}

