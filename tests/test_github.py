from pathlib import Path
from unittest.mock import patch

from app.github import enforce_path_allow_list, resolve_mapping
from app.parser import Incident

FIX_PATHS = ["**/Dockerfile*", "**/*.tf", "**/k8s/**", ".github/workflows/**"]


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


# --- path allow-list enforcement ---

def test_allows_files_matching_fix_paths_and_does_not_revert_them():
    with patch("app.github.changed_files", return_value=["Dockerfile", "k8s/deployment.yaml"]), \
         patch("app.github.discard_file") as mock_discard:
        result = enforce_path_allow_list(Path("/tmp/repo"), FIX_PATHS)

        assert result.allowed == ["Dockerfile", "k8s/deployment.yaml"]
        assert result.reverted == []
        mock_discard.assert_not_called()


def test_allows_nested_devops_files_via_recursive_glob():
    files = ["services/api/Dockerfile", "infra/main.tf", "charts/api/k8s/deployment.yaml"]
    with patch("app.github.changed_files", return_value=files), \
         patch("app.github.discard_file") as mock_discard:
        result = enforce_path_allow_list(Path("/tmp/repo"), FIX_PATHS)

        assert result.allowed == files
        mock_discard.assert_not_called()


def test_reverts_files_outside_fix_paths_eg_application_source_code():
    with patch("app.github.changed_files", return_value=["Dockerfile", "src/index.py"]), \
         patch("app.github.discard_file") as mock_discard:
        result = enforce_path_allow_list(Path("/tmp/repo"), FIX_PATHS)

        assert result.allowed == ["Dockerfile"]
        assert result.reverted == ["src/index.py"]
        mock_discard.assert_called_once_with(Path("/tmp/repo"), "src/index.py")


def test_reverts_everything_when_no_files_match_allow_list():
    with patch("app.github.changed_files", return_value=["README.md"]), \
         patch("app.github.discard_file"):
        result = enforce_path_allow_list(Path("/tmp/repo"), FIX_PATHS)

        assert result.allowed == []
        assert result.reverted == ["README.md"]


# --- repo resolution ---

def test_repo_is_computed_from_github_org_and_namespace(monkeypatch):
    monkeypatch.setattr("app.github.config.GITHUB_ORG", "test-org")
    monkeypatch.setattr("app.github.config.GITHUB_REPO", None)
    monkeypatch.setattr("app.github.config.AWS_REGION", "us-west-2")

    mapping = resolve_mapping(_incident("payments-service"))

    assert mapping.repo == "test-org/payments-service"
    assert mapping.region == "us-west-2"


def test_repo_tracks_whatever_namespace_the_incident_has(monkeypatch):
    monkeypatch.setattr("app.github.config.GITHUB_REPO", None)

    mapping = resolve_mapping(_incident("orders-service"))
    assert mapping.repo.endswith("/orders-service")


def test_github_repo_override_pins_every_incident_to_one_repo(monkeypatch):
    monkeypatch.setattr("app.github.config.GITHUB_REPO", "test-org/fixed-repo")

    mapping_a = resolve_mapping(_incident("payments-service"))
    mapping_b = resolve_mapping(_incident("orders-service"))

    assert mapping_a.repo == "test-org/fixed-repo"
    assert mapping_b.repo == "test-org/fixed-repo"
