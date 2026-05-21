locals {
  common_tags = {
    Project     = var.project
    Environment = var.environment
    Owner       = var.owner
    ManagedBy   = "terraform"
  }

  name_prefix = "${var.project}-${var.environment}"
}

data "aws_availability_zones" "available" {
  state = "available"
}

# -----------------------------------------------------------------------------
# Network (VPC + subnets + IGW + route table) lives in a reusable module so the
# same wiring can be lifted into prod / per-account stacks later.
# -----------------------------------------------------------------------------
module "network" {
  source = "./modules/network"

  vpc_cidr            = var.vpc_cidr
  public_subnet_cidrs = var.public_subnet_cidrs
  azs                 = slice(data.aws_availability_zones.available.names, 0, length(var.public_subnet_cidrs))
  name_prefix         = local.name_prefix
  tags                = local.common_tags
}

# -----------------------------------------------------------------------------
# Web tier security group.
# Inbound 80/443 from the internet is required by the brief and matches a
# normal public web tier. Inbound 22 is restricted via var.ssh_ingress_cidrs.
# -----------------------------------------------------------------------------
resource "aws_security_group" "web" {
  name        = "${local.name_prefix}-web-sg"
  description = "Web tier: HTTP/HTTPS public, SSH restricted"
  vpc_id      = module.network.vpc_id

  ingress {
    description = "HTTP from internet"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH (restricted)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_ingress_cidrs
  }

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-web-sg" })
}

# -----------------------------------------------------------------------------
# Web tier (2 x t3.micro across the two public subnets).
# We pin a known LocalStack-compatible AMI ID rather than data-source it; the
# fake AMIs LocalStack returns don't always filter the way the AWS API does.
# -----------------------------------------------------------------------------
resource "aws_instance" "web" {
  count                       = 2
  ami                         = "ami-0c55b159cbfafe1f0" # placeholder; LocalStack accepts any well-formed AMI id
  instance_type               = var.web_instance_type
  subnet_id                   = module.network.public_subnet_ids[count.index]
  vpc_security_group_ids      = [aws_security_group.web.id]
  associate_public_ip_address = true

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-web-${count.index}"
    Tier = "web"
  })
}

# -----------------------------------------------------------------------------
# S3 bucket for application logs.
# Versioning is enabled and non-current versions expire after 30 days, per brief.
# -----------------------------------------------------------------------------
resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "logs" {
  bucket = "${local.name_prefix}-app-logs-${random_id.bucket_suffix.hex}"
  tags = merge(local.common_tags, {
    Name    = "${local.name_prefix}-app-logs"
    Purpose = "application-logs"
  })
}

resource "aws_s3_bucket_versioning" "logs" {
  bucket = aws_s3_bucket.logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "expire-noncurrent-versions-30d"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  depends_on = [aws_s3_bucket_versioning.logs]
}

# -----------------------------------------------------------------------------
# Intentionally orphan EBS volume.
# The brief asks for an unattached volume so Part B's Janitor has a known
# orphan to find. We deliberately leave the `Owner` tag empty here so the
# untagged-resource detector also fires on it.
# -----------------------------------------------------------------------------
resource "aws_ebs_volume" "orphan" {
  availability_zone = data.aws_availability_zones.available.names[0]
  size              = 10
  type              = "gp3"

  tags = {
    Name        = "${local.name_prefix}-orphan-volume"
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    Note        = "intentional-orphan-for-janitor-demo"
    # Owner intentionally omitted so the tag-policy detector also hits this resource.
  }
}
