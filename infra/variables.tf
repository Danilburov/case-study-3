variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "project" {
  type    = string
  default = "innovatech-lifecycle"
}
variable "vpc_cidr" {
  description = "VPC CIDR"
  type        = string
  default     = "10.0.0.0/16"
}
variable "tags" {
  type        = map(string)
  default = {
    Project = "Innovatech"
    Env     = "dev"
  }
}