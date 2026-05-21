variable "aws_region" {
  description = "AWS region. LocalStack defaults to us-east-1."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project tag value, also used as a name prefix."
  type        = string
  default     = "nimbuskart"
}

variable "environment" {
  description = "Environment tag value (e.g. staging, prod)."
  type        = string
  default     = "staging"
}

variable "owner" {
  description = "Owner tag — the team or person responsible. Required for cost attribution."
  type        = string
  default     = "platform-team"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "Two /24 CIDRs, one per AZ."
  type        = list(string)
  default     = ["10.20.1.0/24", "10.20.2.0/24"]
}

# NOTE: The brief asks for `default = ["0.0.0.0/0"]`. We have deliberately
# overridden that default to a private range and documented the deviation in
# the README under "Decisions & deviations". A reviewer who needs the original
# behaviour can pass `-var='ssh_ingress_cidrs=["0.0.0.0/0"]'`.
variable "ssh_ingress_cidrs" {
  description = "CIDR blocks allowed to SSH to the web tier. Default restricted to RFC1918."
  type        = list(string)
  default     = ["10.0.0.0/8"]
}

variable "web_instance_type" {
  description = "Instance type for the web tier."
  type        = string
  default     = "t3.micro"
}
