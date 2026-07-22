import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.parser import Incident

logger = logging.getLogger("anomaly-agent.k8s")

_VIEW_POLICY_ARN = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"
_ASSUMED_ROLE_ARN_RE = re.compile(r"^arn:aws:sts::(\d+):assumed-role/([^/]+)/.+$")


@dataclass
class IncidentDiagnostics:
    describe_pod: Optional[str] = None
    previous_logs: Optional[str] = None
    current_logs: Optional[str] = None
    events: Optional[str] = None
    deployment_yaml: Optional[str] = None


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


def _safe_kubectl(kubeconfig_path: Path, args: list[str]) -> str:
    try:
        return kubectl(kubeconfig_path, args)
    except RuntimeError as err:
        return f"<error running kubectl {' '.join(args)}: {err}>"


def _resolve_pod_name(kubeconfig_path: Path, namespace: str, workload: str) -> Optional[str]:
    """`workload` may already be a pod name, or a deployment/app label."""
    direct = _safe_kubectl(kubeconfig_path, ["get", "pod", workload, "-n", namespace, "-o", "name"])
    if direct and not direct.startswith("<error"):
        return workload

    by_label = _safe_kubectl(
        kubeconfig_path,
        ["get", "pods", "-n", namespace, "-l", f"app={workload}", "-o", "jsonpath={.items[0].metadata.name}"],
    )
    if by_label and by_label.strip() and not by_label.startswith("<error"):
        return by_label.strip()

    return None


def gather_diagnostics(incident: Incident, kubeconfig_path: Path) -> IncidentDiagnostics:
    namespace, workload = incident.namespace, incident.workload
    pod_name = _resolve_pod_name(kubeconfig_path, namespace, workload)

    describe_pod = _safe_kubectl(kubeconfig_path, ["describe", "pod", pod_name, "-n", namespace]) if pod_name else None
    previous_logs = (
        _safe_kubectl(kubeconfig_path, ["logs", pod_name, "-n", namespace, "--previous", "--tail=200"])
        if pod_name else None
    )
    current_logs = (
        _safe_kubectl(kubeconfig_path, ["logs", pod_name, "-n", namespace, "--tail=200"]) if pod_name else None
    )
    events = _safe_kubectl(
        kubeconfig_path,
        [
            "get", "events", "-n", namespace,
            "--sort-by=.lastTimestamp",
            "--field-selector", f"involvedObject.name={pod_name or workload}",
        ],
    )
    deployment_yaml = _safe_kubectl(kubeconfig_path, ["get", "deployment", workload, "-n", namespace, "-o", "yaml"])

    return IncidentDiagnostics(
        describe_pod=describe_pod,
        previous_logs=previous_logs,
        current_logs=current_logs,
        events=events,
        deployment_yaml=deployment_yaml,
    )
