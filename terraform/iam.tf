data "aws_iam_policy_document" "controller_s3" {
  statement {
    sid    = "ReadWriteConfigurationObjects"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject"
    ]

    resources = [
      "${aws_s3_bucket.config.arn}/blast-radius-guard/configs/*"
    ]
  }

  statement {
    sid    = "ListConfigurationPrefix"
    effect = "Allow"

    actions = [
      "s3:ListBucket"
    ]

    resources = [
      aws_s3_bucket.config.arn
    ]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"

      values = [
        "blast-radius-guard/configs/*"
      ]
    }
  }
}

resource "aws_iam_policy" "controller_s3" {
  name        = "blast-radius-guard-controller-s3"
  description = "Least-privilege S3 access for the Blast-Radius Guard controller"

  policy = data.aws_iam_policy_document.controller_s3.json
}
