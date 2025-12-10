variable "region" {
  type        = string
  description = "AWS region"
  default     = "eu-central-1"
}

variable "project" {
  type        = string
  description = "Base name for Terraform state resources"
  default     = "case-study-3"
}

locals {
  name = var.project
}
