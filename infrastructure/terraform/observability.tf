resource "aws_cloudwatch_log_group" "lambda" {
  for_each = {
    identity_gate   = "${local.name}-schema-identity-gate"
    manifest_loader = "${local.name}-manifest-loader"
  }

  name              = "/aws/lambda/${each.value}"
  retention_in_days = var.environment == "prod" ? 365 : 30
  kms_key_id        = aws_kms_key.data.arn
}

resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-data-alerts"
  kms_master_key_id = aws_kms_key.data.id
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email == null ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "identity_errors" {
  alarm_name          = "${local.name}-identity-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  dimensions          = { FunctionName = aws_lambda_function.identity_gate.function_name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "iterator_age" {
  alarm_name          = "${local.name}-iterator-age"
  namespace           = "AWS/Lambda"
  metric_name         = "IteratorAge"
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 2
  threshold           = 600000
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { FunctionName = aws_lambda_function.identity_gate.function_name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "identity_dlq" {
  alarm_name          = "${local.name}-identity-dlq-visible"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  dimensions          = { QueueName = aws_sqs_queue.identity_dlq.name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "settlement_failure" {
  alarm_name          = "${local.name}-settlement-failed"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.settlement.arn }
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${local.name}-operations"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6,
        properties = {
          title = "Identity-gate errors and age", region = var.aws_region, view = "timeSeries",
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.identity_gate.function_name],
            [".", "IteratorAge", ".", ".", { yAxis = "right", stat = "p95" }]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6,
        properties = {
          title = "Settlement workflow", region = var.aws_region, view = "timeSeries",
          metrics = [
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", aws_sfn_state_machine.settlement.arn],
            [".", "ExecutionTime", ".", ".", { stat = "p95", yAxis = "right" }]
          ]
        }
      }
    ]
  })
}
