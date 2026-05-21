variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
}

variable "public_subnet_cidrs" {
  description = "List of /24 CIDRs, one per AZ."
  type        = list(string)
}

variable "azs" {
  description = "Availability zones to spread subnets across (parallel to public_subnet_cidrs)."
  type        = list(string)
}

variable "name_prefix" {
  description = "Prefix applied to resource Name tags."
  type        = string
}

variable "tags" {
  description = "Common tags applied to every resource in this module."
  type        = map(string)
}
