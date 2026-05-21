#!/usr/bin/env python3
"""
Cost Janitor — scans an AWS account for orphan / wasteful resources.

Detects:
    * Unattached EBS volumes  (status == "available")
    * EC2 instances stopped for more than N days  (default 14)
    * Elastic IPs not associated with any instance
    * Any resource missing one or more required tags

Usage:
    python janitor.py                                  # dry-run (default)
    python janitor.py --delete                         # destructive; respects Protected=true
    python janitor.py --days 30                        # custom stopped-instance threshold
    python janitor.py --endpoint-url http://localhost:4566   # LocalStack
    python janitor.py --region us-west-2 --output-dir ./out

Exit codes:
    0   - no orphans found (dry-run) OR --delete finished
    1   - dry-run found at least one orphan (CI-friendly: makes the job fail)
    2   - bad usage / unrecoverable error
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from constants import (
    EBS_GP2_GB_MONTH_USD,
    EBS_GP3_GB_MONTH_USD,
    EC2_HOURLY_USD,
    EIP_UNUSED_HOURLY_USD,
    HOURS_PER_MONTH,
    PROTECTED_TAG_KEY,
    PROTECTED_TAG_VALUE,
    REQUIRED_TAGS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("janitor")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    """One row in the report. Mirrors the schema documented in the brief."""

    resource_id: str
    resource_type: str
    reason: str
    age_days: int | None
    estimated_monthly_cost_usd: float
    tags: dict[str, Any]
    suggested_action: str
    safe_to_auto_delete: bool
    region: str = "us-east-1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def build_clients(region: str, endpoint_url: str | None) -> dict[str, Any]:
    cfg = Config(region_name=region, retries={"max_attempts": 3, "mode": "standard"})
    kw: dict[str, Any] = {"config": cfg}
    if endpoint_url:
        kw.update(
            endpoint_url=endpoint_url,
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
    return {
        "ec2": boto3.client("ec2", **kw),
        "sts": boto3.client("sts", **kw),
    }


def normalize_tags(tag_list: list[dict[str, str]] | None) -> dict[str, str]:
    if not tag_list:
        return {}
    return {t["Key"]: t.get("Value", "") for t in tag_list}


def missing_required_tags(tags: dict[str, str]) -> list[str]:
    return [t for t in REQUIRED_TAGS if not tags.get(t)]


def is_protected(tags: dict[str, str]) -> bool:
    return tags.get(PROTECTED_TAG_KEY) == PROTECTED_TAG_VALUE


def parse_state_transition_age(reason_str: str) -> int | None:
    """
    AWS embeds the stop time in StateTransitionReason like:
        "User initiated (2024-11-12 14:00:00 GMT)"
    Returns the age in days, or None if it can't be parsed.
    """
    if not reason_str:
        return None
    m = re.search(r"\((\d{4}-\d{2}-\d{2})", reason_str)
    if not m:
        return None
    try:
        d = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - d).days


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------
def find_unattached_ebs(ec2) -> list[Finding]:
    findings: list[Finding] = []
    paginator = ec2.get_paginator("describe_volumes")
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for vol in page.get("Volumes", []):
            tags = normalize_tags(vol.get("Tags"))
            age_days = (datetime.now(timezone.utc) - vol["CreateTime"]).days
            size_gb = vol["Size"]
            vtype = vol.get("VolumeType", "gp3")
            unit = EBS_GP2_GB_MONTH_USD if vtype == "gp2" else EBS_GP3_GB_MONTH_USD
            cost = round(size_gb * unit, 2)

            missing = missing_required_tags(tags)
            reason = "unattached"
            if missing:
                reason += f"; missing_tags={','.join(missing)}"

            findings.append(
                Finding(
                    resource_id=vol["VolumeId"],
                    resource_type="ebs_volume",
                    reason=reason,
                    age_days=age_days,
                    estimated_monthly_cost_usd=cost,
                    tags=tags,
                    suggested_action="delete",
                    safe_to_auto_delete=(age_days >= 7 and not is_protected(tags)),
                )
            )
    return findings


def find_stopped_instances(ec2, max_days: int) -> list[Finding]:
    findings: list[Finding] = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
    ):
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                tags = normalize_tags(inst.get("Tags"))
                # Prefer the actual stop time from StateTransitionReason; fall
                # back to LaunchTime, which is conservative (overestimates age).
                age_days = parse_state_transition_age(inst.get("StateTransitionReason", ""))
                if age_days is None:
                    age_days = (datetime.now(timezone.utc) - inst["LaunchTime"]).days

                if age_days < max_days:
                    continue

                itype = inst.get("InstanceType", "t3.micro")
                hourly = EC2_HOURLY_USD.get(itype, EC2_HOURLY_USD["t3.micro"])
                # Stopped instances incur EBS cost but not compute. We report
                # the upper bound (compute equivalent) because that's the
                # cost the team would avoid by terminating.
                cost = round(hourly * HOURS_PER_MONTH, 2)

                missing = missing_required_tags(tags)
                reason = f"stopped_for_{age_days}_days"
                if missing:
                    reason += f"; missing_tags={','.join(missing)}"

                findings.append(
                    Finding(
                        resource_id=inst["InstanceId"],
                        resource_type="ec2_instance",
                        reason=reason,
                        age_days=age_days,
                        estimated_monthly_cost_usd=cost,
                        tags=tags,
                        suggested_action="terminate",
                        # Terminate is irreversible; never auto-do it.
                        safe_to_auto_delete=False,
                    )
                )
    return findings


def find_unassociated_eips(ec2) -> list[Finding]:
    findings: list[Finding] = []
    addresses = ec2.describe_addresses().get("Addresses", [])
    for addr in addresses:
        if addr.get("AssociationId"):
            continue
        tags = normalize_tags(addr.get("Tags"))
        cost = round(EIP_UNUSED_HOURLY_USD * HOURS_PER_MONTH, 2)

        missing = missing_required_tags(tags)
        reason = "unassociated"
        if missing:
            reason += f"; missing_tags={','.join(missing)}"

        findings.append(
            Finding(
                resource_id=addr.get("AllocationId") or addr.get("PublicIp", ""),
                resource_type="elastic_ip",
                reason=reason,
                age_days=None,
                estimated_monthly_cost_usd=cost,
                tags=tags,
                suggested_action="release",
                safe_to_auto_delete=(not is_protected(tags)),
            )
        )
    return findings


def find_untagged_resources(ec2) -> list[Finding]:
    """
    Resources missing one or more required tags.

    The orphan detectors above already flag missing tags on their hits. This
    scanner catches resources that aren't otherwise orphan-shaped — e.g. a
    running, fully-attached EC2 with no Owner tag.
    """
    findings: list[Finding] = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["running", "pending"]}]
    ):
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                tags = normalize_tags(inst.get("Tags"))
                missing = missing_required_tags(tags)
                if not missing:
                    continue

                itype = inst.get("InstanceType", "t3.micro")
                hourly = EC2_HOURLY_USD.get(itype, EC2_HOURLY_USD["t3.micro"])
                cost = round(hourly * HOURS_PER_MONTH, 2)
                age_days = (datetime.now(timezone.utc) - inst["LaunchTime"]).days

                findings.append(
                    Finding(
                        resource_id=inst["InstanceId"],
                        resource_type="ec2_instance",
                        reason=f"missing_required_tags={','.join(missing)}",
                        age_days=age_days,
                        estimated_monthly_cost_usd=cost,
                        tags=tags,
                        suggested_action="add_tags",
                        safe_to_auto_delete=False,
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Destructive actions
# ---------------------------------------------------------------------------
def apply_deletions(ec2, findings: list[Finding]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for f in findings:
        if is_protected(f.tags):
            actions.append(
                {"resource_id": f.resource_id, "action": "skipped", "reason": "Protected=true"}
            )
            continue
        if not f.safe_to_auto_delete:
            actions.append(
                {
                    "resource_id": f.resource_id,
                    "action": "skipped",
                    "reason": "not safe_to_auto_delete",
                }
            )
            continue
        try:
            if f.resource_type == "ebs_volume":
                ec2.delete_volume(VolumeId=f.resource_id)
                actions.append({"resource_id": f.resource_id, "action": "deleted"})
            elif f.resource_type == "elastic_ip":
                ec2.release_address(AllocationId=f.resource_id)
                actions.append({"resource_id": f.resource_id, "action": "released"})
            else:
                actions.append(
                    {
                        "resource_id": f.resource_id,
                        "action": "skipped",
                        "reason": "no auto-delete path for this type",
                    }
                )
        except (ClientError, BotoCoreError) as exc:
            actions.append(
                {"resource_id": f.resource_id, "action": "error", "error": str(exc)}
            )
    return actions


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Cost Janitor Report",
        "",
        f"- **Scan time:** {report['scan_timestamp']}",
        f"- **Account:** `{report['account_id']}` (`{report['region']}`)",
        f"- **Mode:** `{report['mode']}`",
        f"- **Total orphans:** {summary['total_orphans']}",
        f"- **Estimated monthly waste:** ${summary['estimated_monthly_waste_usd']:.2f}",
        "",
        "## Findings",
        "",
    ]
    if not report["findings"]:
        lines.append("_No orphans found. NimbusKart looking lean._ ")
        return "\n".join(lines) + "\n"

    lines += [
        "| Resource ID | Type | Reason | Age (d) | $/mo | Suggested action | Safe auto-delete |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in report["findings"]:
        age = f["age_days"] if f["age_days"] is not None else "—"
        lines.append(
            f"| `{f['resource_id']}` | {f['resource_type']} | {f['reason']} | "
            f"{age} | ${f['estimated_monthly_cost_usd']:.2f} | "
            f"{f['suggested_action']} | {'yes' if f['safe_to_auto_delete'] else 'no'} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Cost Janitor — find and optionally clean up wasteful AWS resources."
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Detect only, do not delete (default).",
    )
    mode.add_argument(
        "--delete",
        dest="delete",
        action="store_true",
        help="Actually delete orphans (skips anything tagged Protected=true).",
    )
    p.add_argument(
        "--days",
        type=int,
        default=14,
        help="Stopped-instance age threshold in days (default 14).",
    )
    p.add_argument("--region", default="us-east-1")
    p.add_argument(
        "--endpoint-url",
        default=None,
        help="Override AWS endpoint, e.g. http://localhost:4566 for LocalStack.",
    )
    p.add_argument("--output-dir", default=".")
    args = p.parse_args(argv)
    # If neither flag was passed, default to dry-run.
    if not args.delete:
        args.dry_run = True
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    clients = build_clients(args.region, args.endpoint_url)
    ec2, sts = clients["ec2"], clients["sts"]

    try:
        account_id = sts.get_caller_identity()["Account"]
    except (ClientError, BotoCoreError) as exc:
        log.warning("get_caller_identity failed (%s); using placeholder account id", exc)
        account_id = "000000000000"

    findings: list[Finding] = []
    findings += find_unattached_ebs(ec2)
    findings += find_stopped_instances(ec2, args.days)
    findings += find_unassociated_eips(ec2)
    findings += find_untagged_resources(ec2)

    total_waste = round(sum(f.estimated_monthly_cost_usd for f in findings), 2)

    report = {
        "scan_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "account_id": account_id,
        "region": args.region,
        "mode": "delete" if args.delete else "dry-run",
        "summary": {
            "total_orphans": len(findings),
            "estimated_monthly_waste_usd": total_waste,
        },
        "findings": [asdict(f) for f in findings],
    }

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (out_dir / "report.md").write_text(render_markdown(report))

    if args.delete:
        actions = apply_deletions(ec2, findings)
        (out_dir / "actions.json").write_text(json.dumps(actions, indent=2))
        log.info("Delete pass complete: %d actions logged", len(actions))

    log.info(
        "Findings: %d | est. monthly waste: $%.2f | mode: %s",
        len(findings),
        total_waste,
        report["mode"],
    )
    log.info("Wrote %s and %s", out_dir / "report.json", out_dir / "report.md")

    # CI signal: dry-run with orphans → non-zero exit so the workflow fails.
    if args.dry_run and len(findings) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
