"""
Pricing constants and tag-policy values used by the Cost Janitor.

Pricing sources (us-east-1, on-demand; verified at time of writing — production
should swap these for the AWS Pricing API):

    - EBS gp3 / gp2:     https://aws.amazon.com/ebs/pricing/
    - EC2 on-demand:     https://aws.amazon.com/ec2/pricing/on-demand/
    - Unassociated EIP:  https://aws.amazon.com/vpc/pricing/   ($0.005/hour
                         for an Elastic IP not associated with a running
                         instance, effective Feb 2024)

We use the AWS billing convention of 730 hours/month.
"""

HOURS_PER_MONTH = 730

# Storage ($/GB-month)
EBS_GP3_GB_MONTH_USD = 0.08
EBS_GP2_GB_MONTH_USD = 0.10

# Compute ($/hour, us-east-1 on-demand)
EC2_HOURLY_USD = {
    "t3.micro":  0.0104,
    "t3.small":  0.0208,
    "t3.medium": 0.0416,
    "t3.large":  0.0832,
    "t3.xlarge": 0.1664,
    "m5.large":  0.096,
}

# Idle Elastic IPs ($/hour)
EIP_UNUSED_HOURLY_USD = 0.005

# Tag policy — every resource that supports tags must carry these three
# (plus ManagedBy, which is checked separately because Terraform owns it).
REQUIRED_TAGS = ["Project", "Environment", "Owner"]

# Resources tagged Protected=true are never destroyed even in --delete mode.
PROTECTED_TAG_KEY = "Protected"
PROTECTED_TAG_VALUE = "true"
