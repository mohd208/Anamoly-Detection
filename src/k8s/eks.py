import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger("anomaly-agent.eks")

_VIEW_POLICY_ARN = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"

_ASSUMED_ROLE_ARN_RE = re.compile(r"^arn:aws:sts::(\d+):assumed-role/([^/]+)/.+$")


def _self_role_arn() -> str:
    """The EC2 instance's own IAM role ARN, derived from STS. `aws sts
    get-caller-identity` returns an "assumed-role" session ARN
    (arn:aws:sts::ACCOUNT:assumed-role/ROLE/SESSION) - EKS access entries need
    the underlying role ARN (arn:aws:iam::ACCOUNT:role/ROLE) instead."""
    result = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--query", "Arn", "--output", "text"],
        check=True,
        capture_output=True,
        text=True,
    )
    arn = result.stdout.strip()
    match = _ASSUMED_ROLE_ARN_RE.match(arn)
    if not match:
        return arn  # already a plain IAM role/user ARN
    account_id, role_name = match.groups()
    return f"arn:aws:iam::{account_id}:role/{role_name}"


def ensure_cluster_access(cluster: str, region: str) -> None:
    """Self-grants this instance's IAM role read-only EKS access (an access
    entry + AmazonEKSViewPolicy) on `cluster`, if it doesn't already have it.
    AWS IAM permissions (e.g. AdministratorAccess) only cover the AWS API side
    - EKS keeps a separate, per-cluster RBAC layer that IAM admin does not
    imply, by design. This makes that grant automatic instead of a manual
    one-time step per cluster. Safe/idempotent to call every time."""
    role_arn = _self_role_arn()

    create = subprocess.run(
        [
            "aws", "eks", "create-access-entry",
            "--cluster-name", cluster,
            "--region", region,
            "--principal-arn", role_arn,
            "--type", "STANDARD",
        ],
        capture_output=True,
        text=True,
    )
    if create.returncode == 0:
        logger.info("Granted new EKS access entry for %s on cluster %s", role_arn, cluster)
    elif "ResourceInUseException" not in create.stderr:
        raise RuntimeError(f"Failed to create EKS access entry for {cluster}: {create.stderr.strip()}")

    associate = subprocess.run(
        [
            "aws", "eks", "associate-access-policy",
            "--cluster-name", cluster,
            "--region", region,
            "--principal-arn", role_arn,
            "--policy-arn", _VIEW_POLICY_ARN,
            "--access-scope", "type=cluster",
        ],
        capture_output=True,
        text=True,
    )
    if associate.returncode != 0:
        raise RuntimeError(f"Failed to associate EKS view policy for {cluster}: {associate.stderr.strip()}")


def ensure_kubeconfig(cluster: str, region: str, workdir: Path) -> Path:
    """Generates a kubeconfig for the given cluster using the EC2 instance's IAM
    role (via IMDSv2 -> STS -> `aws eks get-token`, wired up automatically by
    `aws eks update-kubeconfig`). No long-lived credentials are stored or
    passed around. `ensure_cluster_access` runs first so no manual per-cluster
    setup is needed - see deploy/eks-access-entry.md for what that grant does
    under the hood."""
    ensure_cluster_access(cluster, region)

    workdir.mkdir(parents=True, exist_ok=True)
    kubeconfig_path = workdir / f"kubeconfig-{cluster}"

    try:
        subprocess.run(
            [
                "aws", "eks", "update-kubeconfig",
                "--name", cluster,
                "--region", region,
                "--kubeconfig", str(kubeconfig_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as err:
        raise RuntimeError(
            f"aws eks update-kubeconfig failed for cluster={cluster} region={region}: "
            f"{err.stderr.strip() or err.stdout.strip()}"
        ) from err

    return kubeconfig_path


def kubectl(kubeconfig_path: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["kubectl", "--kubeconfig", str(kubeconfig_path), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as err:
        raise RuntimeError(
            f"kubectl {' '.join(args)} failed: {err.stderr.strip() or err.stdout.strip()}"
        ) from err

    return result.stdout
