import subprocess
from pathlib import Path


def ensure_kubeconfig(cluster: str, region: str, workdir: Path) -> Path:
    """Generates a kubeconfig for the given cluster using the EC2 instance's IAM
    role (via IMDSv2 -> STS -> `aws eks get-token`, wired up automatically by
    `aws eks update-kubeconfig`). No long-lived credentials are stored or
    passed around - see deploy/eks-access-entry.md for the one-time IAM/RBAC
    setup this depends on."""
    workdir.mkdir(parents=True, exist_ok=True)
    kubeconfig_path = workdir / f"kubeconfig-{cluster}"

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
    return kubeconfig_path


def kubectl(kubeconfig_path: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["kubectl", "--kubeconfig", str(kubeconfig_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout
