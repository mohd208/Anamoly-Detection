from pathlib import Path
from typing import Optional

from src.incident.types import Incident, IncidentDiagnostics
from src.k8s.eks import kubectl


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
