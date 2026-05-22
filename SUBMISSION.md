# Submission — DevOps Engineer Assignment

Harshit Sharma
hsharma212502@gmail.com
23-05-2026
6-8 Hours

## Deliverables checklist

- [ ] Part A: Terraform code under /terraform applies cleanly on LocalStack
- [ ] Part A: `terraform validate` and `terraform fmt -check` both pass
- [ ] Part B: Janitor script runs in --dry-run mode and produces report.json
- [ ] Part B: GitHub Actions workflow runs green on a fresh PR
- [ ] Part B: --delete mode respects Protected=true tag
- [ ] Part C: DESIGN.md is present and within 2 pages
- [ ] Walkthrough video link below is accessible (unlisted is fine)

## Walkthrough video

https://www.loom.com/share/aa8129cfae804c8992395eb03b33a71b


## Known limitations

- Stopped-EC2 age is best-effort: AWS does not expose a `StoppedAt` field, so
  the script parses `StateTransitionReason` and falls back to `LaunchTime`.
  Production should join against CloudTrail `StopInstances` events.
- Cost numbers are static (us-east-1, on-demand) — see `janitor/constants.py`.
  Real deploy would call the AWS Pricing API with a daily cache.
- AMI for the web tier is a pinned placeholder ID; for real AWS this should
  be a `data "aws_ami"` lookup against the latest Amazon Linux 2 SSM parameter.
- Only 4 orphan types covered (the four required). Snapshots, NAT GWs, idle
  ALBs, RDS, and S3-without-lifecycle are the obvious next four.
- Janitor's `--delete` mode never auto-terminates EC2 (irreversible). It will
  suggest, log, and skip with a clear reason.

## AI usage disclosure

(see Section 7 of the brief)

**Tools used and roughly what for:**
<e.g. Claude Sonnet for the Terraform module skeleton and Janitor detector
loops; ChatGPT to debug a moto pagination edge case; Copilot for small
completions in the workflow YAML.>

**One thing the AI got wrong (and how I noticed):**
<e.g. it suggested `boto3.resource('ec2').volumes.filter(...)` which silently
drops results past page 1; I switched to `get_paginator('describe_volumes')`
after the unit test against a stress fixture came back short.>

**One section I wrote without AI help — and why:**
<e.g. `parse_state_transition_age` and its tests; I wanted to own the regex
and the failure modes around malformed AWS reason strings since this is the
only piece of the code that gates whether an instance gets terminated.>
