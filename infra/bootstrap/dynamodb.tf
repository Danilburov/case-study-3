#dynamoDB table for terraform state locking
resource "aws_dynamodb_table" "tf_locks" {
  name         = "${local.name}-tf-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Project     = local.name
    Environment = "dev"
    Purpose     = "terraform-locks"
  }
}
