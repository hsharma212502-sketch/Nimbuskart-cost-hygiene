output "vpc_id" {
  description = "VPC ID."
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs."
  value       = aws_subnet.public[*].id
}

output "internet_gateway_id" {
  description = "IGW ID."
  value       = aws_internet_gateway.this.id
}
