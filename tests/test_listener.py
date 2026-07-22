from app.listener import _extract_text_from_event


def test_extracts_plain_top_level_text():
    event = {"text": "cluster_name:c1 kube_namespace:ns1 pod_name:pod1"}
    assert _extract_text_from_event(event) == "cluster_name:c1 kube_namespace:ns1 pod_name:pod1"


def test_extracts_text_from_legacy_attachments():
    event = {
        "text": "",
        "attachments": [
            {"fallback": "cluster_name:c1 kube_namespace:ns1 pod_name:pod1", "pretext": "Triggered"}
        ],
    }
    text = _extract_text_from_event(event)
    assert "cluster_name:c1 kube_namespace:ns1 pod_name:pod1" in text
    assert "Triggered" in text


def test_extracts_text_from_nested_block_kit_elements():
    # Mirrors Datadog's rich "Mute Monitor"/"Declare Incident" card shape:
    # a section block plus a context block with nested text elements.
    event = {
        "text": "",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Critical Kubernetes Incident*"},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "cluster_name:c1"},
                    {"type": "mrkdwn", "text": "kube_namespace:ns1 pod_name:pod1"},
                ],
            },
        ],
    }
    text = _extract_text_from_event(event)
    assert "Critical Kubernetes Incident" in text
    assert "cluster_name:c1" in text
    assert "kube_namespace:ns1 pod_name:pod1" in text


def test_returns_empty_string_when_nothing_present():
    assert _extract_text_from_event({}) == ""
    assert _extract_text_from_event({"text": "", "blocks": [], "attachments": []}) == ""
