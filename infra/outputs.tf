output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "hr_db_endpoint" {
  value = aws_db_instance.hr.address
}

output "hr_db_port" {
  value = aws_db_instance.hr.port
}
output "hr_db_endpoint" {
  value = aws_db_instance.hr.address
}

output "hr_db_port" {
  value = aws_db_instance.hr.port
}
