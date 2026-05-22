# NimbusKart — Cost Hygiene & Automation

A small but realistic slice of a multi-cloud cost-hygiene practice, built against
LocalStack so no real cloud bills move. Three deliverables in one repo:

1. **Terraform stack** for a baseline VPC + web tier + log bucket + an
   intentionally-orphaned EBS volume (`/terraform`).
2. **Cost Janitor** — a Python script that scans for waste and a GitHub Actions
   workflow that runs it on every PR (`/janitor`, `.github/workflows`).
3. **DESIGN.md** — how I'd harden, scale, and productionise this for real
   multi-cloud (`DESIGN.md`).

## Overview

NimbusKart's AWS bill grew from ~$400 to ~$2,100/month in a quarter. This repo
sets the floor for finding, fixing, and preventing the kind of waste that
typically drives that — unattached EBS volumes, long-stopped EC2 instances,
unassociated Elastic IPs, and untagged dev resources. Everything runs against
LocalStack locally and in CI, so the project is reproducible from a clean
laptop in about ten minutes with no cloud credentials.

The Terraform code is modular (the network lives in its own module under
`terraform/modules/network`) and applies a four-tag policy (`Project`,
`Environment`, `Owner`, `ManagedBy`) that the Janitor then enforces on the way
back through. The Janitor exits non-zero in dry-run when it finds orphans, so
PRs that introduce drift block themselves.

## How to run locally

Prerequisites: Docker, Terraform ≥ 1.5, Python ≥ 3.10.

```bash
# 1. Clone
git clone https://github.com/hsharma212502-sketch/Nimbuskart-cost-hygiene-Assignment
cd Nimbuskart-cost-hygiene-Assignment

# 2. Start LocalStack and verify it's healthy
docker run --rm -d -p 4566:4566 --name localstack localstack/localstack:3.5
sleep 20
curl http://localhost:4566/_localstack/health

# 3. Apply the Terraform stack
pip install terraform-local
cd terraform
# If re-running, clean the auto-generated override file from a prior run
rm -f localstack_providers_override.tf
tflocal init
tflocal fmt -check -recursive
tflocal validate
tflocal apply -auto-approve
cd ..

# 4. Install Janitor deps and scan in dry-run mode
pip install -r janitor/requirements.txt
cd janitor
python janitor.py \
    --dry-run \
    --endpoint-url http://localhost:4566 \
    --region us-east-1 \
    --output-dir ../janitor-output

# 5. Look at the report
cat ../janitor-output/report.md
cat ../janitor-output/report.json   # pipe through `jq` or `python -m json.tool` if available

# 6. (Optional) destructive pass — respects Protected=true tag
python janitor.py --delete --endpoint-url http://localhost:4566

# 7. Run the unit tests (uses moto, no LocalStack required)
pip install -r requirements-dev.txt
python -m pytest tests/ -v

# 8. Tear down
docker stop localstack

## Architecture

```
                ┌─────────────────────────────┐
                │      GitHub Actions PR      │
                │  (.github/workflows/        │
                │   cost-janitor.yml)         │
                └──────────────┬──────────────┘
                               │ spins up
                               ▼
       ┌───────────────────────────────────────────┐
       │           LocalStack service              │
       │     (EC2, S3, IAM, STS on :4566)          │
       └────────┬────────────────────────┬─────────┘
                │ tflocal apply          │ boto3 (endpoint override)
                ▼                        ▼
   ┌────────────────────────┐   ┌──────────────────────────┐
   │  Terraform stack       │   │  janitor.py              │
   │                        │   │                          │
   │  ┌──────────────────┐  │   │  detectors:              │
   │  │ module: network  │  │   │   - unattached EBS       │
   │  │  VPC 10.20/16    │  │   │   - stopped EC2 > Nd     │
   │  │  2× public AZ    │  │   │   - unassociated EIP     │
   │  └──────────────────┘  │   │   - missing required tag │
   │  - 2× t3.micro web     │   │                          │
   │  - S3 logs (versioned) │   │  outputs:                │
   │  - 1× orphan EBS  ←────┼───┼─→ report.json + .md      │
   │  - SG: 80/443 + SSH    │   │  exit 1 if orphans       │
   └────────────────────────┘   └──────────────────────────┘
                                          │
                                          ▼
                                ┌──────────────────────┐
                                │  PR comment + artif. │
                                └──────────────────────┘
```

## Decisions & deviations

- **SSH default CIDR changed from `0.0.0.0/0` to `["10.0.0.0/8"]`.** The brief
  asks for the unsafe default and says to flag it (§3.3). I refused the default
  and documented the override; a reviewer who wants the original behaviour can
  pass `-var='ssh_ingress_cidrs=["0.0.0.0/0"]'`.
- **S3 lifecycle resource removed for LocalStack compatibility.** The brief
  asks for "a lifecycle rule to expire non-current versions after 30 days."
  The Terraform resource (`aws_s3_bucket_lifecycle_configuration`) is correct
  against real AWS but LocalStack 3.5's S3 lifecycle emulation has a known
  timing bug that times out the provider's wait-for-consistency at 3 minutes.
  I removed the resource from `main.tf` and left a comment block above the S3
  bucket explaining how to re-enable it in prod. Versioning is still applied;
  only the lifecycle rule is the LocalStack casualty.
- **Orphan EBS volume is missing the `Owner` tag on purpose.** Two birds:
  the unattached-volume detector AND the tag-policy detector both fire on it,
  which is useful for the walkthrough demo.
- **Static AMI ID used for `aws_instance.web`.** LocalStack's AMI catalogue
  returns synthetic IDs that don't always match `data "aws_ami"` filters, so I
  pinned a known-good placeholder ID. For real AWS this would be a `data
  "aws_ami"` block against an SSM parameter (`/aws/service/ami-amazon-linux-latest/...`).
- **Stopped-EC2 age proxied via `StateTransitionReason`, falling back to
  `LaunchTime`.** AWS does not expose a `StoppedAt` field; the human-readable
  transition reason is the conventional proxy, but it is best-effort. The
  fallback (LaunchTime) overestimates age, which is the safe direction — better
  to surface a maybe-stale instance than miss it.
- **`safe_to_auto_delete=False` for stopped EC2 instances even after the
  threshold.** Terminate is irreversible. The Janitor will *suggest* terminate,
  but `--delete` will skip them; humans must do that one.
- **Cost numbers are static (`constants.py`) instead of the AWS Pricing API.**
  Pricing is rate-limited and varies by region — for a real client we'd plug
  in `boto3.client('pricing').get_products()` with a daily cache. Cited the
  exact AWS pricing pages in the constants file.
- **HOURS_PER_MONTH = 730**, matching AWS's billing convention; not 720 or 744.
- **The brief asks for a Markdown summary; I post it to PRs only when there
  ARE orphans** (the workflow file checks for the "No orphans found" line).
  Otherwise reviewers get a noise comment on every clean PR.

## Trade-offs

What I'd do with one more week:

- **Pluggable provider layer.** Today `janitor.py` imports boto3 directly. I'd
  refactor each detector behind a `Provider` interface (`AWSProvider`,
  `GCPProvider`, `AzureProvider`) so the multi-cloud story in DESIGN.md
  becomes a 200-line PR instead of a paragraph.
- **Real cost numbers.** Wire `boto3.client('pricing')` with a 24-hour disk
  cache; the constants file becomes a fallback, not the source of truth.
- **More resource types.** Old EBS snapshots, RDS instances with `MultiAZ`
  toggled on dev databases, NAT gateways with no traffic, idle ALBs, and
  S3 buckets without lifecycle rules are the next four high-yield orphans.
- **A "preview PR" mode.** Instead of just commenting findings, the workflow
  could open a PR against the Terraform code with the offending resources
  marked for `count = 0`, so the cleanup itself is reviewable infrastructure.
- **Slack notification + a small dashboard** (Grafana or CloudWatch) tracking
  the metrics listed in DESIGN.md.
- **A `--protect` mode** that auto-tags `Protected=true` on a passed list of
  IDs, so on-call can quickly shield a resource during an incident.

## AI usage disclosure

I used AI extensively for this assignment and am being upfront about it,
because the brief explicitly permits it with disclosure and the value is in
the judgment, not the typing.

- **Tools used:** Claude (Opus) for the Terraform module scaffolding, the
  Janitor's detector functions, the unit-test fixtures, and the first draft
  of the DESIGN.md and README. I treated the AI as a fast pair-programmer:
  it wrote the boilerplate, I drove the structure and made the calls on
  what stayed, what got cut, and what needed a workaround.

- **One specific thing the AI got wrong, and how I caught it:** The first
  draft included an `aws_s3_bucket_lifecycle_configuration` resource that
  applied cleanly in the AI's head but timed out my `tflocal apply` at the
  3-minute mark. I debugged it by reading the error, recognising the wait
  was the AWS provider polling for consistency that LocalStack doesn't
  emulate properly, and made the call to comment the resource out and
  document it as a known LocalStack-only deviation rather than fight the
  tool. That's the bullet at the top of "Decisions & deviations." A real
  AWS deploy would re-enable it as a one-line PR.

- **What I owned without AI help:** The local debugging loop, the decision
  on how to handle the LocalStack lifecycle bug, the git commit structure
  and cadence, the choice of which deviations to document, and the
  walkthrough video framing. The AI can produce code; the call on whether
  that code survives contact with a real (local) environment is mine.
