# Cost Janitor Report

- **Scan time:** 2026-05-21T11:13:32Z
- **Account:** `123456789012` (`us-east-1`)
- **Mode:** `dry-run`
- **Total orphans:** 3
- **Estimated monthly waste:** $12.04

## Findings

| Resource ID | Type | Reason | Age (d) | $/mo | Suggested action | Safe auto-delete |
|---|---|---|---|---|---|---|
| `vol-b99247f8` | ebs_volume | unattached; missing_tags=Project,Environment,Owner | 0 | $0.80 | delete | no |
| `eipalloc-4ecd22fe` | elastic_ip | unassociated; missing_tags=Project,Environment,Owner | — | $3.65 | release | yes |
| `i-50be2d111b38f2999` | ec2_instance | missing_required_tags=Project,Environment,Owner | 0 | $7.59 | add_tags | no |
