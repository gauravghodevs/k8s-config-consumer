
# 2. DynamoDB Table (Satisfies JD "database services" at $0 cost)
resource "aws_dynamodb_table" "rollout_audit" {
  name         = "blast-radius-rollout-audit"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "rollout_id"
  range_key    = "timestamp"

  attribute {
    name = "rollout_id"
    type = "S"
  }
  attribute {
    name = "timestamp"
    type = "S"
  }
  tags = { Project = "blast-radius" }
}

# 3. AWS Glue Catalog Database & Table (Satisfies JD "Glue" at $0 cost)
resource "aws_glue_catalog_database" "audit_db" {
  name = "blast_radius_audit_db"
}

resource "aws_glue_catalog_table" "rollout_events" {
  name          = "rollout_events"
  database_name = aws_glue_catalog_database.audit_db.name
  table_type    = "EXTERNAL_TABLE"

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.config.id}/blast-radius-guard/audit/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      name                  = "json-serde"
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "rollout_id"
      type = "string"
    }
    columns {
      name = "candidate"
      type = "string"
    }
    columns {
      name = "state"
      type = "string"
    }
    columns {
      name = "slo_remaining_budget_pct"
      type = "double"
    }
    columns {
      name = "sha256"
      type = "string"
    }
    columns {
      name = "timestamp"
      type = "string"
    }
  }
}

# 4. CloudWatch Alarm on Lambda Errors (Triggers CodeDeploy Auto-Remediation Rollback)
resource "aws_cloudwatch_metric_alarm" "lambda_error_alarm" {
  alarm_name          = "blast-radius-validator-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  dimensions = {
    FunctionName = aws_lambda_function.config_validator.function_name
    Resource     = "${aws_lambda_function.config_validator.function_name}:${aws_lambda_alias.live.name}"
  }
  tags = { Project = "blast-radius" }
}

# 5. CodeDeploy Application & Canary Deployment Group for Lambda
resource "aws_iam_role" "codedeploy_role" {
  name = "blast-radius-codedeploy-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "codedeploy.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "codedeploy_lambda" {
  role       = aws_iam_role.codedeploy_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSCodeDeployRoleForLambda"
}

resource "aws_codedeploy_app" "validator_app" {
  compute_platform = "Lambda"
  name             = "blast-radius-validator-app"
}

resource "aws_codedeploy_deployment_group" "validator_canary" {
  app_name               = aws_codedeploy_app.validator_app.name
  deployment_group_name  = "blast-radius-validator-canary-dg"
  service_role_arn       = aws_iam_role.codedeploy_role.arn
  deployment_config_name = "CodeDeployDefault.LambdaCanary10Percent5Minutes"

  deployment_style {
    deployment_option = "WITH_TRAFFIC_CONTROL"
    deployment_type   = "BLUE_GREEN"
  }

  alarm_configuration {
    alarms  = [aws_cloudwatch_metric_alarm.lambda_error_alarm.alarm_name]
    enabled = true
  }

  auto_rollback_configuration {
    enabled = true
    events  = ["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM"]
  }
}

# 6. CodeBuild Role & Project
resource "aws_iam_role" "codebuild_role" {
  name = "blast-radius-codebuild-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "codebuild_policy" {
  name = "blast-radius-codebuild-policy"
  role = aws_iam_role.codebuild_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:GetBucketLocation"]
        Resource = ["${aws_s3_bucket.config.arn}", "${aws_s3_bucket.config.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["codebuild:CreateReportGroup", "codebuild:CreateReport", "codebuild:UpdateReport", "codebuild:BatchPutTestCases"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_codebuild_project" "blast_radius_build" {
  name          = "blast-radius-bash-build"
  service_role  = aws_iam_role.codebuild_role.arn
  build_timeout = 10

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/amazonlinux2-x86_64-standard:5.0"
    type            = "LINUX_CONTAINER"
    privileged_mode = true

    environment_variable {
      name  = "ECR_REPO_URI"
      value = aws_ecr_repository.consumer.repository_url
    }
  }

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.config.id}/source/repo.zip"
    buildspec = "buildspec.yml"
  }
  tags = { Project = "blast-radius" }
}

output "ecr_repository_url" {
  value = aws_ecr_repository.consumer.repository_url
}
