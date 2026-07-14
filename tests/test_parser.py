from unittest.mock import patch

from src.incident.parser import parse_incident


def test_extracts_fields_from_datadog_style_tag_text_without_calling_claude():
    text = (
        "[Triggered] Pod CrashLoopBackOff cluster_name:prod-eks "
        "kube_namespace:payments pod_name:payments-7f9c8"
    )

    with patch("src.incident.parser.run_claude_json") as mock_claude:
        incident = parse_incident(channel="C123", ts="111.222", text=text)

        assert incident is not None
        assert incident.cluster == "prod-eks"
        assert incident.namespace == "payments"
        assert incident.workload == "payments-7f9c8"
        assert incident.alert_type == "CrashLoopBackOff"
        mock_claude.assert_not_called()


def test_detects_oom_and_image_pull_alert_types():
    oom = parse_incident(
        channel="C1", ts="1", text="OOMKilled cluster_name:c1 kube_namespace:ns1 pod_name:pod1"
    )
    assert oom.alert_type == "OOMKilled"

    pull_err = parse_incident(
        channel="C1", ts="2", text="ImagePullBackOff cluster_name:c1 kube_namespace:ns1 pod_name:pod1"
    )
    assert pull_err.alert_type == "ImagePullBackOff"


def test_falls_back_to_claude_and_returns_none_if_that_also_fails():
    with patch("src.incident.parser.run_claude_json", return_value={}) as mock_claude:
        incident = parse_incident(channel="C1", ts="3", text="Something went wrong with the payments pod")

        mock_claude.assert_called_once()
        assert incident is None


def test_uses_claude_fallback_result_when_it_fills_in_missing_fields():
    fallback = {"cluster": "prod-eks", "namespace": "payments", "workload": "payments-api"}
    with patch("src.incident.parser.run_claude_json", return_value=fallback):
        incident = parse_incident(channel="C1", ts="4", text="Something went wrong with the payments pod")

        assert incident.cluster == "prod-eks"
        assert incident.namespace == "payments"
        assert incident.workload == "payments-api"
