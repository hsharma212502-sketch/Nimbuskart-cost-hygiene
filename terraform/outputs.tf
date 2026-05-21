output "vpc_id" {
  description = "ID of the NimbusKart staging VPC."
  value       = module.network.vpc_id
}

output "public_subnet_ids" {
  description = "Public subnet IDs (one per AZ)."
  value       = module.network.public_subnet_ids
}

output "s3_logs_bucket" {
  description = "Name of the application-logs S3 bucket."
  value       = aws_s3_bucket.logs.bucket
}

output "web_instance_ids" {
  description = "IDs of the two web-tier EC2 instances."
  value       = aws_instance.web[*].id
}

output "orphan_ebs_volume_id" {
  description = "ID of the deliberately-orphan EBS volume (Janitor target)."
  value       = aws_ebs_volume.orphan.id
}
