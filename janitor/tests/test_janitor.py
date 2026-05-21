"""
Unit tests for the Cost Janitor.

These run against `moto`, which mocks AWS APIs at the SDK level — no LocalStack
container needed. They cover the four detector types plus the tag-policy logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

# Make the parent package importable when pytest is run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from janitor import (  # noqa: E402
    find_stopped_instances,
    find_unassociated_eips,
    find_unattached_ebs,
    find_untagged_resources,
    is_protected,
    missing_required_tags,
    normalize_tags,
    parse_state_transition_age,
)


# ---------------------------------------------------------------------------
# Pure helpers — no AWS mocks needed
# ---------------------------------------------------------------------------
def test_normalize_tags_handles_none_and_empty():
    assert normalize_tags(None) == {}
    assert normalize_tags([]) == {}
    assert normalize_tags([{"Key": "A", "Value": "1"}]) == {"A": "1"}


def test_missing_required_tags():
    assert set(missing_required_tags({})) == {"Project", "Environment", "Owner"}
    assert missing_required_tags(
        {"Project": "x", "Environment": "y", "Owner": "z"}
    ) == []
    # Empty-string values count as missing.
    assert missing_required_tags(
        {"Project": "x", "Environment": "", "Owner": "z"}
    ) == ["Environment"]


def test_is_protected():
    assert is_protected({"Protected": "true"}) is True
    assert is_protected({"Protected": "false"}) is False
    assert is_protected({}) is False


def test_parse_state_transition_age_handles_garbage():
    assert parse_state_transition_age("") is None
    assert parse_state_transition_age("User initiated") is None
    assert parse_state_transition_age(None) is None


# ---------------------------------------------------------------------------
# Detector tests (moto)
# ---------------------------------------------------------------------------
@mock_aws
def test_unattached_ebs_detected_and_costed():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.create_volume(
        AvailabilityZone="us-east-1a",
        Size=20,
        VolumeType="gp3",
        TagSpecifications=[
            {
                "ResourceType": "volume",
                "Tags": [
                    {"Key": "Project", "Value": "nimbuskart"},
                    {"Key": "Environment", "Value": "staging"},
                    {"Key": "Owner", "Value": "platform"},
                ],
            }
        ],
    )
    findings = find_unattached_ebs(ec2)
    assert len(findings) == 1
    f = findings[0]
    assert f.resource_type == "ebs_volume"
    assert f.reason == "unattached"
    # 20 GB * $0.08 = $1.60
    assert f.estimated_monthly_cost_usd == pytest.approx(1.60)


@mock_aws
def test_unattached_ebs_reports_missing_tags():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.create_volume(AvailabilityZone="us-east-1a", Size=10, VolumeType="gp3")
    findings = find_unattached_ebs(ec2)
    assert len(findings) == 1
    assert "missing_tags" in findings[0].reason


@mock_aws
def test_unassociated_eip_detected():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.allocate_address(Domain="vpc")
    findings = find_unassociated_eips(ec2)
    assert len(findings) == 1
    assert findings[0].resource_type == "elastic_ip"
    assert findings[0].suggested_action == "release"


@mock_aws
def test_untagged_running_instance_flagged():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.run_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro"
    )
    findings = find_untagged_resources(ec2)
    assert any(f.resource_type == "ec2_instance" for f in findings)


@mock_aws
def test_fully_tagged_running_instance_not_flagged():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Project", "Value": "nimbuskart"},
                    {"Key": "Environment", "Value": "staging"},
                    {"Key": "Owner", "Value": "platform"},
                ],
            }
        ],
    )
    findings = find_untagged_resources(ec2)
    assert findings == []


@mock_aws
def test_stopped_instance_below_threshold_skipped():
    # A freshly-stopped instance is younger than the default 14-day threshold,
    # so it should NOT be reported.
    ec2 = boto3.client("ec2", region_name="us-east-1")
    r = ec2.run_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro"
    )
    iid = r["Instances"][0]["InstanceId"]
    ec2.stop_instances(InstanceIds=[iid])
    findings = find_stopped_instances(ec2, max_days=14)
    assert findings == []
