from src.github.repo_map import resolve_mapping
from src.incident.types import Incident


def _incident(namespace: str) -> Incident:
    return Incident(
        slack_message_ts="1",
        slack_channel="C1",
        cluster="prod-eks",
        namespace=namespace,
        workload="payments-api",
        alert_type="CrashLoopBackOff",
        title="t",
        raw_text="t",
        detected_at="2026-01-01T00:00:00+00:00",
    )


def test_repo_is_computed_from_github_org_and_namespace(monkeypatch):
    monkeypatch.setattr("src.github.repo_map.config.GITHUB_ORG", "test-org")
    monkeypatch.setattr("src.github.repo_map.config.GITHUB_REPO", None)
    monkeypatch.setattr("src.github.repo_map.config.AWS_REGION", "us-west-2")

    mapping = resolve_mapping(_incident("payments-service"))

    assert mapping.repo == "test-org/payments-service"
    assert mapping.region == "us-west-2"


def test_repo_tracks_whatever_namespace_the_incident_has(monkeypatch):
    monkeypatch.setattr("src.github.repo_map.config.GITHUB_REPO", None)

    mapping = resolve_mapping(_incident("orders-service"))
    assert mapping.repo.endswith("/orders-service")


def test_github_repo_override_pins_every_incident_to_one_repo(monkeypatch):
    monkeypatch.setattr("src.github.repo_map.config.GITHUB_REPO", "test-org/fixed-repo")

    mapping_a = resolve_mapping(_incident("payments-service"))
    mapping_b = resolve_mapping(_incident("orders-service"))

    assert mapping_a.repo == "test-org/fixed-repo"
    assert mapping_b.repo == "test-org/fixed-repo"
