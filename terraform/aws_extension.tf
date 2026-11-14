resource "aws_s3_bucket_notification" "eb_notification" {
  bucket      = aws_s3_bucket.config.id
  eventbridge = true
}

resource "aws_iam_role" "lambda_exec" {
  name = "blast-radius-bash-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = { Project = "blast-radius" }
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_s3_read" {
  name = "blast-radius-lambda-s3-read"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${aws_s3_bucket.config.arn}/blast-radius-guard/configs/*"
    }]
  })
}

resource "aws_lambda_function" "config_validator" {
  function_name    = "blast-radius-config-validator"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "bootstrap"
  runtime          = "provided.al2023"
  filename         = "${path.module}/../config-validator-lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/../config-validator-lambda.zip")
  timeout          = 15
  memory_size      = 128
  publish          = true

  tags = { Project = "blast-radius" }

  lifecycle {
    ignore_changes = [
      filename,
      source_code_hash
    ]
  }
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.config_validator.function_name
  function_version = aws_lambda_function.config_validator.version

  lifecycle {
    ignore_changes = [function_version]
  }
}

resource "aws_cloudwatch_event_rule" "s3_config_upload" {
  name        = "blast-radius-s3-config-created"
  description = "Trigger validator on config upload"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.config.id] }
      object = { key = [{ prefix = "blast-radius-guard/configs/" }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "invoke_validator" {
  rule      = aws_cloudwatch_event_rule.s3_config_upload.name
  target_id = "BashConfigValidator"
  arn       = aws_lambda_alias.live.arn
}

resource "aws_lambda_permission" "allow_eb" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.config_validator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.s3_config_upload.arn
  qualifier     = aws_lambda_alias.live.name
}

resource "aws_apigatewayv2_api" "validate_api" {
  name          = "blast-radius-validate-api"
  protocol_type = "HTTP"
  tags          = { Project = "blast-radius" }
}

resource "aws_apigatewayv2_integration" "lambda_int" {
  api_id                 = aws_apigatewayv2_api.validate_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.live.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "post_validate" {
  api_id             = aws_apigatewayv2_api.validate_api.id
  route_key          = "POST /validate"
  target             = "integrations/${aws_apigatewayv2_integration.lambda_int.id}"
  authorization_type = "AWS_IAM"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.validate_api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_apigw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.config_validator.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.validate_api.execution_arn}/*/*"
  qualifier     = aws_lambda_alias.live.name
}

output "validate_api_endpoint" {
  value = "${aws_apigatewayv2_api.validate_api.api_endpoint}/validate"
}
