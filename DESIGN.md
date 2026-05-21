# DESIGN.md — Productionising the Cost Janitor

This is the "if NimbusKart actually pays us for this" version. Two pages.

---

## 1. Multi-cloud reality

GCP next quarter, Azure later. The trick is to make each cloud a leaf, not a
fork in the road.

**Module boundaries:**

```
janitor/
├── core/
│   ├── finding.py        # Finding dataclass + JSON schema (cloud-agnostic)
│   ├── report.py         # render_markdown, render_json, render_csv
│   ├── policy.py         # tag policy, Protected logic, safe_to_auto_delete rules
│   └── runner.py         # iterates providers, aggregates findings, exits
└── providers/
    ├── base.py           # abstract Provider class
    ├── aws/
    │   ├── client.py     # boto3 session, endpoint override
    │   └── detectors/    # one file per orphan pattern
    ├── gcp/              # mirrors aws/, uses google-cloud-* libs
    └── azure/            # mirrors aws/, uses azure-mgmt-*
```

Each `Provider` exposes the same surface: `list_unattached_disks()`,
`list_stopped_compute(min_age_days)`, `list_idle_ips()`, `list_untagged()`. The
runner doesn't care which cloud answered; it just collates `Finding` objects
and asks `policy.py` whether each one is safe to delete.

Pricing also gets its own module (`pricing/`) per provider, because each cloud
has its own price API and SKU vocabulary. Findings carry a normalised
`estimated_monthly_cost_usd` and that's the only number the report cares about.

**What you gain:** adding GCP is "write `providers/gcp/`", not "rewrite the
janitor." What you give up: a thin layer of indirection, plus the cost of
keeping the abstract Provider interface honest (different clouds have
different concepts — GCP `Disk` is closer to AWS EBS than to Azure
ManagedDisk; you'll fight that abstraction at the seams).

---

## 2. Permissions — minimal IAM for dry-run

In `--dry-run` mode the Janitor only describes. The minimum AWS managed policy
gives away too much (`ReadOnlyAccess` reads S3 object contents). Custom is
shorter and safer:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DryRunDescribeOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVolumes",
        "ec2:DescribeInstances",
        "ec2:DescribeAddresses",
        "ec2:DescribeTags",
        "ec2:DescribeRegions",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

For `--delete` mode, add a second statement with `ec2:DeleteVolume` and
`ec2:ReleaseAddress`, scoped with a tag condition so the Janitor cannot
destroy anything that lacks its expected `ManagedBy` tag (defence in depth
against a hijacked role):

```json
{
  "Sid": "DeleteOnlyTaggedResources",
  "Effect": "Allow",
  "Action": ["ec2:DeleteVolume", "ec2:ReleaseAddress"],
  "Resource": "*",
  "Condition": {
    "StringNotEquals": {"aws:ResourceTag/Protected": "true"}
  }
}
```

The IAM role itself runs under a dedicated `janitor-readonly` /
`janitor-writeer` pair (CI assumes the read role; humans assume the write role
through SSO with MFA).

---

## 3. Safety net — two ways naïve auto-deletion would burn NimbusKart

**Failure mode A: "Available" doesn't mean "unused."**
An EBS volume in state `available` can be 30 seconds old — a volume that was
just *detached* during an instance refresh and is queued to be re-attached.
Deleting it during the refresh window causes a permanent data loss outage on
the resurrected instance. Guardrail: require `age_days >= 7` AND a "no recent
attachment events" check against CloudTrail (or a simpler proxy: `Owner` tag
present) before allowing auto-delete. The current code already requires
age ≥ 7; production should add the CloudTrail lookback.

**Failure mode B: "Stopped" doesn't mean "abandoned."**
A common pattern at startups is "stop the staging cluster on Friday, start it
Monday." A naïve 14-day threshold survives that pattern, but a 7-day threshold
would terminate someone's holiday at week 2 of PTO. Worse: terminate is
irreversible, and root EBS goes with it. Guardrails: (a) `safe_to_auto_delete`
is hard-coded `False` for `ec2_instance` regardless of age — the Janitor
suggests, a human terminates; (b) before any human-driven terminate, take a
final AMI snapshot and tag it `auto-snapshot-pre-terminate` with 30-day TTL.

(There are more — orphan ENIs that are actually about to be attached by an
ASG, EIPs reserved for an upcoming DR drill, etc. The pattern is the same: a
short-term "looks idle" signal is not enough.)

---

## 4. Observability — five metrics, where they go, what triggers

| # | Metric                            | Source                       | Sink            | Alert threshold                                   |
|---|-----------------------------------|------------------------------|-----------------|---------------------------------------------------|
| 1 | `janitor.orphans.count`           | report.json `total_orphans`  | CloudWatch (PutMetricData) → Grafana | > 50 OR week-over-week +30% |
| 2 | `janitor.waste.usd_monthly`       | report.json `summary.estimated_monthly_waste_usd` | CloudWatch + Slack | > $500/month sustained for 3 days |
| 3 | `janitor.run.success`             | workflow run status          | CloudWatch alarm | any failure → page FinOps on-call                 |
| 4 | `janitor.delete.skipped_protected`| actions.json `skipped:Protected=true` | CloudWatch | > 10/day = someone is over-tagging                |
| 5 | `janitor.tag_compliance.percent`  | (1 − untagged / total) × 100 | Grafana panel   | < 90% → opens a ticket, not a page                |

Metric 2 is the one the CFO cares about. Metrics 3 and 4 are the safety
metrics: a silent failure is worse than a noisy one, and a Janitor that
suddenly skips 100 deletions probably means someone tagged the whole prod
account `Protected=true` as a "temporary fix."

---

## 5. What I did not build

I scoped this to AWS-only, four orphan types, single-account, single-region,
static pricing, and a per-PR scan. I left out: (a) RDS, NAT gateways,
snapshots, and idle ALBs — the second tier of high-yield orphans — because
each is a separate detector with its own price math and the brief asked for
four; (b) cross-account assume-role wiring, because LocalStack doesn't model
trust policies usefully and a fake demo would be worse than no demo; (c) the
pluggable Provider interface from §1, because shipping it half-built would
make the AWS code uglier without the multi-cloud payoff; (d) Slack/PagerDuty
integrations, because a working PR comment proves the loop and the rest is
plumbing. I'd add them in the order listed.
