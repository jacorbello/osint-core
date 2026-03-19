"""Tests for the Celery notification worker task."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from osint_core.workers.notify import (
    _SEVERITY_TO_COLOR,
    _build_slack_blocks,
    _dispatch_channel,
    _needs_db_fetch,
    _post_to_slack,
    _render_webhook_payload,
    send_notification,
)

# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


def test_send_notification_task_registered():
    """The send_notification task should be registered with the correct name."""
    assert send_notification.name == "osint.send_notification"


def test_send_notification_task_max_retries():
    """The send_notification task should have max_retries=3."""
    assert send_notification.max_retries == 3


def test_send_notification_is_bound():
    """The send_notification task should be a bound task (bind=True)."""
    assert send_notification.__bound__ is True


# ---------------------------------------------------------------------------
# _needs_db_fetch helper
# ---------------------------------------------------------------------------


def test_needs_db_fetch_none():
    """None event_data should trigger DB fetch."""
    assert _needs_db_fetch(None) is True


def test_needs_db_fetch_empty_dict():
    """Empty dict should trigger DB fetch."""
    assert _needs_db_fetch({}) is True


def test_needs_db_fetch_partial_data():
    """Dict missing required fields should trigger DB fetch."""
    assert _needs_db_fetch({"severity": "high", "title": "T"}) is True


def test_needs_db_fetch_none_values():
    """Dict with None values for required fields should trigger DB fetch."""
    data = {"severity": "high", "title": None, "summary": "S", "source_id": "x"}
    assert _needs_db_fetch(data) is True


def test_needs_db_fetch_complete_data():
    """Dict with all required fields should not trigger DB fetch."""
    assert _needs_db_fetch({
        "severity": "high",
        "title": "T",
        "summary": "S",
        "source_id": "nvd",
    }) is False


# ---------------------------------------------------------------------------
# Threshold / skip logic
# ---------------------------------------------------------------------------


def test_below_threshold_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Events below the configured threshold should not trigger a notification."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "high")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "test-token")

    result = send_notification.run(
        "evt-001",
        {"severity": "low", "title": "Minor event", "summary": "Nothing to see here.",
         "source_id": "test"},
    )

    assert result["notified"] is False
    assert "below threshold" in result["reason"]
    assert result["event_id"] == "evt-001"


def test_above_threshold_sends_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    """Events at or above the threshold should send a Gotify notification."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "medium")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "test-token")
    monkeypatch.setenv("OSINT_GOTIFY_URL", "http://gotify-test/message")

    with patch("osint_core.workers.notify._post_to_gotify", return_value=True) as mock_post:
        result = send_notification.run(
            "evt-002",
            {
                "severity": "high",
                "title": "CVE-2026-9999 critical",
                "summary": "A critical vulnerability was found.",
                "source_id": "nvd",
                "event_type": "cve",
                "indicators": ["CVE-2026-9999", "192.168.1.1"],
            },
        )

    assert result["notified"] is True
    assert result["event_id"] == "evt-002"
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    # Priority should be 8 for "high"
    assert call_kwargs.args[2] == 8


def test_exact_threshold_severity_notifies(monkeypatch: pytest.MonkeyPatch) -> None:
    """An event exactly at the threshold should be dispatched."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "medium")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    with patch("osint_core.workers.notify._post_to_gotify", return_value=True) as mock_post:
        result = send_notification.run(
            "evt-003",
            {"severity": "medium", "title": "Medium alert", "summary": "Some info.",
             "source_id": "test"},
        )

    assert result["notified"] is True
    mock_post.assert_called_once()


def test_missing_severity_treated_as_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """If severity is absent the event is treated as 'info' and skipped by default."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "medium")

    # Provide complete data to avoid DB fetch attempt.
    result = send_notification.run("evt-004", {
        "title": "T", "summary": "S", "source_id": "x", "severity": None,
    })

    assert result["notified"] is False


# ---------------------------------------------------------------------------
# DB fallback — event_data is None
# ---------------------------------------------------------------------------


def test_db_fetch_when_event_data_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """When event_data is None, the task should fetch from DB and use those fields."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    db_data = {
        "title": "DB Title",
        "summary": "DB Summary",
        "severity": "high",
        "source_id": "nvd",
        "event_type": "cve",
        "indicators": ["CVE-2026-1234"],
    }

    mock_fetch = patch(
        "osint_core.workers.notify._fetch_event_data",
        new_callable=AsyncMock, return_value=db_data,
    )
    mock_gotify = patch(
        "osint_core.workers.notify._post_to_gotify", return_value=True,
    )
    with mock_fetch, mock_gotify as mock_post:
        result = send_notification.run("evt-db-1", None)

    assert result["notified"] is True
    assert result["event_id"] == "evt-db-1"
    mock_post.assert_called_once()


def test_db_fetch_supplements_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """When event_data is missing title/summary, DB data should supplement."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    # Caller provides severity but no title/summary.
    partial_data = {"severity": "critical"}

    db_data = {
        "title": "DB Title",
        "summary": "DB Summary",
        "severity": "high",  # Should NOT overwrite caller's "critical".
        "source_id": "nvd",
        "event_type": "cve",
        "indicators": ["CVE-2026-5678"],
    }

    mock_fetch = patch(
        "osint_core.workers.notify._fetch_event_data",
        new_callable=AsyncMock, return_value=db_data,
    )
    mock_gotify = patch(
        "osint_core.workers.notify._post_to_gotify", return_value=True,
    )
    with mock_fetch, mock_gotify as mock_post:
        result = send_notification.run("evt-db-2", partial_data)

    assert result["notified"] is True
    # Priority should be 10 for "critical" (caller's severity, not DB's "high").
    call_args = mock_post.call_args
    assert call_args.args[2] == 10


def test_db_fetch_failure_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DB fetch fails, task should fall back to available data gracefully."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    mock_fetch = patch(
        "osint_core.workers.notify._fetch_event_data",
        new_callable=AsyncMock, return_value=None,
    )
    mock_gotify = patch(
        "osint_core.workers.notify._post_to_gotify", return_value=True,
    )
    with mock_fetch, mock_gotify:
        # event_data=None and DB returns None — still works with defaults.
        result = send_notification.run("evt-db-3", None)

    # Severity falls back to "info" which is below "low" threshold.
    assert result["notified"] is False
    assert result["event_id"] == "evt-db-3"


def test_db_fetch_failure_graceful_with_partial_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DB fetch fails but partial data exists, task uses what it has."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    partial = {"severity": "high"}

    mock_fetch = patch(
        "osint_core.workers.notify._fetch_event_data",
        new_callable=AsyncMock, return_value=None,
    )
    mock_gotify = patch(
        "osint_core.workers.notify._post_to_gotify", return_value=True,
    )
    with mock_fetch, mock_gotify as mock_post:
        result = send_notification.run("evt-db-4", partial)

    assert result["notified"] is True
    assert result["event_id"] == "evt-db-4"
    mock_post.assert_called_once()


def test_no_db_fetch_when_data_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    """When event_data has all required fields, no DB fetch should happen."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    complete_data = {
        "severity": "high",
        "title": "Complete Title",
        "summary": "Complete Summary",
        "source_id": "nvd",
        "event_type": "cve",
        "indicators": ["CVE-2026-0001"],
    }

    mock_fetch_p = patch(
        "osint_core.workers.notify._fetch_event_data",
        new_callable=AsyncMock,
    )
    mock_gotify = patch(
        "osint_core.workers.notify._post_to_gotify", return_value=True,
    )
    with mock_fetch_p as mock_fetch, mock_gotify:
        result = send_notification.run("evt-db-5", complete_data)

    mock_fetch.assert_not_called()
    assert result["notified"] is True


# ---------------------------------------------------------------------------
# Gotify unreachable — retry
# ---------------------------------------------------------------------------


def test_gotify_unreachable_triggers_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """When Gotify fails and no other channel succeeds, the task should retry."""
    import httpx

    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")
    monkeypatch.delenv("OSINT_SLACK_WEBHOOK_URL", raising=False)

    mock_self = MagicMock()
    mock_self.request.retries = 0
    mock_self.retry.side_effect = Exception("retried")

    with patch(
        "osint_core.workers.notify._post_to_gotify",
        side_effect=httpx.ConnectError("connection refused"),
    ), pytest.raises(Exception, match="retried"):
        send_notification.run.__func__(
            mock_self,
            "evt-005",
            {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
        )

    mock_self.retry.assert_called_once()


# ---------------------------------------------------------------------------
# Missing token
# ---------------------------------------------------------------------------


def test_no_channels_configured_returns_not_notified(monkeypatch: pytest.MonkeyPatch) -> None:
    """If no notification channels are configured, return notified=False."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.delenv("OSINT_GOTIFY_TOKEN", raising=False)
    monkeypatch.delenv("OSINT_SLACK_WEBHOOK_URL", raising=False)

    result = send_notification.run(
        "evt-006",
        {"severity": "critical", "title": "Critical!", "summary": "Very bad.",
         "source_id": "test"},
    )

    assert result["notified"] is False
    assert result["event_id"] == "evt-006"
    assert "no notification channels configured" in result["reason"]


# ---------------------------------------------------------------------------
# Webhook channel — _render_webhook_payload
# ---------------------------------------------------------------------------


def test_render_webhook_payload_default_template():
    """The default template should produce valid JSON with event fields."""
    from osint_core.workers.notify import _DEFAULT_WEBHOOK_TEMPLATE

    context = {
        "title": "Test Alert",
        "severity": "high",
        "summary": "Something happened.",
        "source_id": "nvd",
        "event_type": "cve",
        "indicators": ["CVE-2026-0001"],
    }
    rendered = _render_webhook_payload(_DEFAULT_WEBHOOK_TEMPLATE, context)
    parsed = json.loads(rendered)
    assert parsed["title"] == "Test Alert"
    assert parsed["severity"] == "high"
    assert parsed["indicators"] == ["CVE-2026-0001"]


def test_render_webhook_payload_custom_template():
    """A custom Jinja2 template should render event fields."""
    template = "Alert: {{ title }} ({{ severity }})"
    context = {"title": "CVE found", "severity": "critical"}
    rendered = _render_webhook_payload(template, context)
    assert rendered == "Alert: CVE found (critical)"


def test_render_webhook_payload_json_escaping():
    """Jinja2 tojson filter should properly escape special characters."""
    template = '{"msg": {{ summary | tojson }}}'
    context = {"summary": 'He said "hello" & <bye>'}
    rendered = _render_webhook_payload(template, context)
    parsed = json.loads(rendered)
    assert parsed["msg"] == 'He said "hello" & <bye>'


# ---------------------------------------------------------------------------
# Webhook channel — _dispatch_channel
# ---------------------------------------------------------------------------


def test_dispatch_channel_gotify():
    """dispatch_channel with type=gotify should call _post_to_gotify."""
    channel = {"type": "gotify"}
    msg = {"title": "T", "body": "B"}
    event_data = {"title": "T", "severity": "high"}

    with patch("osint_core.workers.notify._post_to_gotify", return_value=True) as mock:
        result = _dispatch_channel(channel, msg=msg, event_data=event_data, priority=8)

    assert result is True
    mock.assert_called_once_with("T", "B", 8)


def test_dispatch_channel_webhook():
    """dispatch_channel with type=webhook should call _post_to_webhook."""
    channel = {
        "type": "webhook",
        "url": "https://hooks.example.com/alert",
        "method": "POST",
        "headers": {"Authorization": "Bearer secret"},
        "payload_template": '{"alert": {{ title | tojson }}}',
    }
    msg = {"title": "T", "body": "B"}
    event_data = {"title": "CVE Alert", "severity": "high"}

    with patch("osint_core.workers.notify._post_to_webhook", return_value=True) as mock:
        result = _dispatch_channel(channel, msg=msg, event_data=event_data, priority=8)

    assert result is True
    mock.assert_called_once()
    call_kwargs = mock.call_args
    assert call_kwargs.args[0] == "https://hooks.example.com/alert"
    assert call_kwargs.kwargs["method"] == "POST"
    assert call_kwargs.kwargs["headers"] == {"Authorization": "Bearer secret"}
    assert '"CVE Alert"' in call_kwargs.kwargs["payload"]


def test_dispatch_channel_webhook_missing_url():
    """dispatch_channel with type=webhook but no url should return False."""
    channel = {"type": "webhook"}
    msg = {"title": "T", "body": "B"}
    result = _dispatch_channel(channel, msg=msg, event_data={}, priority=5)
    assert result is False


def test_dispatch_channel_unknown_type():
    """dispatch_channel with an unknown type should raise ValueError."""
    channel = {"type": "carrier_pigeon"}
    msg = {"title": "T", "body": "B"}
    with pytest.raises(ValueError, match="Unknown notification channel type"):
        _dispatch_channel(channel, msg=msg, event_data={}, priority=5)


# ---------------------------------------------------------------------------
# Webhook end-to-end via send_notification
# ---------------------------------------------------------------------------


def test_webhook_channel_dispatched(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_notification should dispatch to a webhook channel from plan YAML."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")

    channels = [
        {
            "type": "webhook",
            "url": "https://hooks.example.com/osint",
            "headers": {"X-Api-Key": "abc123"},
        },
    ]

    with patch("osint_core.workers.notify._post_to_webhook", return_value=True) as mock_wh:
        result = send_notification.run(
            "evt-wh-1",
            {
                "severity": "high",
                "title": "Webhook Test",
                "summary": "Testing webhook channel.",
                "source_id": "test",
                "event_type": "alert",
                "indicators": [],
            },
            channels=channels,
        )

    assert result["notified"] is True
    assert result["event_id"] == "evt-wh-1"
    mock_wh.assert_called_once()
    call_kwargs = mock_wh.call_args
    assert call_kwargs.args[0] == "https://hooks.example.com/osint"
    assert call_kwargs.kwargs["headers"] == {"X-Api-Key": "abc123"}


def test_webhook_5xx_triggers_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 5xx response from a webhook should trigger a Celery retry."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")

    mock_self = MagicMock()
    mock_self.request.retries = 0
    mock_self.retry.side_effect = Exception("retried")

    response = httpx.Response(502, request=httpx.Request("POST", "https://example.com"))
    error = httpx.HTTPStatusError("Bad Gateway", request=response.request, response=response)

    channels = [{"type": "webhook", "url": "https://hooks.example.com/fail"}]

    with patch(
        "osint_core.workers.notify._post_to_webhook", side_effect=error,
    ), pytest.raises(Exception, match="retried"):
        send_notification.run.__func__(
            mock_self,
            "evt-wh-retry",
            {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
            channels=channels,
        )

    mock_self.retry.assert_called_once()


def test_webhook_connect_error_triggers_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection error from a webhook should trigger a Celery retry."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")

    mock_self = MagicMock()
    mock_self.request.retries = 0
    mock_self.retry.side_effect = Exception("retried")

    channels = [{"type": "webhook", "url": "https://hooks.example.com/down"}]

    with patch(
        "osint_core.workers.notify._post_to_webhook",
        side_effect=httpx.ConnectError("connection refused"),
    ), pytest.raises(Exception, match="retried"):
        send_notification.run.__func__(
            mock_self,
            "evt-wh-conn",
            {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
            channels=channels,
        )

    mock_self.retry.assert_called_once()


def test_webhook_custom_payload_template(monkeypatch: pytest.MonkeyPatch) -> None:
    """A custom payload_template should be rendered with event fields."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")

    channels = [
        {
            "type": "webhook",
            "url": "https://hooks.example.com/slack",
            "payload_template": '{"text": "{{ severity }}: {{ title }}"}',
        },
    ]

    with patch("osint_core.workers.notify._post_to_webhook", return_value=True) as mock_wh:
        result = send_notification.run(
            "evt-wh-tpl",
            {
                "severity": "critical",
                "title": "Major Incident",
                "summary": "Big problem.",
                "source_id": "test",
            },
            channels=channels,
        )

    assert result["notified"] is True
    call_kwargs = mock_wh.call_args
    payload = call_kwargs.kwargs["payload"]
    parsed = json.loads(payload)
    assert parsed["text"] == "critical: Major Incident"


def test_multiple_channels_mixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_notification should dispatch to multiple channels."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    channels = [
        {"type": "gotify"},
        {"type": "webhook", "url": "https://hooks.example.com/a"},
    ]

    with (
        patch("osint_core.workers.notify._post_to_gotify", return_value=True) as mock_g,
        patch("osint_core.workers.notify._post_to_webhook", return_value=True) as mock_w,
    ):
        result = send_notification.run(
            "evt-multi",
            {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
            channels=channels,
        )

    assert result["notified"] is True
    mock_g.assert_called_once()
    mock_w.assert_called_once()


def test_no_channels_falls_back_to_gotify(monkeypatch: pytest.MonkeyPatch) -> None:
    """When channels is None, send_notification falls back to Gotify."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    with patch("osint_core.workers.notify._post_to_gotify", return_value=True) as mock_g:
        result = send_notification.run(
            "evt-fallback",
            {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
            # channels not passed — default None
        )

    assert result["notified"] is True
    mock_g.assert_called_once()


# ---------------------------------------------------------------------------
# Return shape
# ---------------------------------------------------------------------------


def test_return_shape_when_notified(monkeypatch: pytest.MonkeyPatch) -> None:
    """The return dict must have event_id, notified, and reason keys."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    with patch("osint_core.workers.notify._post_to_gotify", return_value=True):
        result = send_notification.run(
            "evt-007",
            {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
        )

    assert set(result.keys()) >= {"event_id", "notified", "reason"}


def test_return_shape_when_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The return dict must have event_id, notified, and reason keys when skipped."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "critical")

    result = send_notification.run(
        "evt-008",
        {"severity": "low", "title": "T", "summary": "S", "source_id": "x"},
    )

    assert set(result.keys()) >= {"event_id", "notified", "reason"}
    assert result["notified"] is False


# ---------------------------------------------------------------------------
# Slack Block Kit message formatting
# ---------------------------------------------------------------------------


class TestBuildSlackBlocks:
    """Tests for _build_slack_blocks() message formatting."""

    def test_basic_structure(self) -> None:
        """Payload should contain attachments with color and blocks."""
        payload = _build_slack_blocks(
            title="Test Alert",
            summary="Something happened.",
            severity="high",
            indicators=[],
        )
        assert "attachments" in payload
        assert len(payload["attachments"]) == 1
        att = payload["attachments"][0]
        assert "color" in att
        assert "blocks" in att

    def test_severity_color_mapping(self) -> None:
        """Each severity should map to its expected color."""
        for sev, expected_color in _SEVERITY_TO_COLOR.items():
            payload = _build_slack_blocks("T", "S", sev, [])
            assert payload["attachments"][0]["color"] == expected_color

    def test_unknown_severity_falls_back_to_info_color(self) -> None:
        """Unknown severity should use the info color."""
        payload = _build_slack_blocks("T", "S", "unknown", [])
        assert payload["attachments"][0]["color"] == _SEVERITY_TO_COLOR["info"]

    def test_title_and_summary_in_first_block(self) -> None:
        """Title and summary should appear in the first section block."""
        payload = _build_slack_blocks("My Title", "My Summary", "critical", [])
        first_block = payload["attachments"][0]["blocks"][0]
        assert first_block["type"] == "section"
        assert "*My Title*" in first_block["text"]["text"]
        assert "My Summary" in first_block["text"]["text"]

    def test_severity_field_present(self) -> None:
        """The severity field should appear in the second section block."""
        payload = _build_slack_blocks("T", "S", "high", [])
        fields_block = payload["attachments"][0]["blocks"][1]
        assert fields_block["type"] == "section"
        sev_field = fields_block["fields"][0]
        assert "HIGH" in sev_field["text"]

    def test_indicators_included(self) -> None:
        """Indicators should appear as a field when provided."""
        payload = _build_slack_blocks("T", "S", "high", ["CVE-2026-0001", "10.0.0.1"])
        fields = payload["attachments"][0]["blocks"][1]["fields"]
        assert len(fields) == 2  # severity + indicators
        ind_field = fields[1]
        assert "CVE-2026-0001" in ind_field["text"]
        assert "10.0.0.1" in ind_field["text"]

    def test_no_indicators_field_when_empty(self) -> None:
        """When no indicators provided, only severity field should be present."""
        payload = _build_slack_blocks("T", "S", "medium", [])
        fields = payload["attachments"][0]["blocks"][1]["fields"]
        assert len(fields) == 1  # severity only

    def test_indicators_truncated_above_ten(self) -> None:
        """More than 10 indicators should be truncated with a count."""
        indicators = [f"IOC-{i}" for i in range(15)]
        payload = _build_slack_blocks("T", "S", "high", indicators)
        ind_field = payload["attachments"][0]["blocks"][1]["fields"][1]
        assert "(+5 more)" in ind_field["text"]
        # First 10 should be present
        assert "IOC-0" in ind_field["text"]
        assert "IOC-9" in ind_field["text"]


# ---------------------------------------------------------------------------
# _post_to_slack
# ---------------------------------------------------------------------------


class TestPostToSlack:
    """Tests for _post_to_slack() webhook dispatch."""

    def test_empty_url_returns_false(self) -> None:
        """An empty webhook URL should return False without making a request."""
        result = _post_to_slack("", "T", "S", "high", [])
        assert result is False

    def test_successful_post(self) -> None:
        """A successful POST should return True."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch("osint_core.workers.notify.httpx.post", return_value=mock_resp):
            result = _post_to_slack(
                "https://hooks.slack.com/services/T/B/X",
                "Alert Title",
                "Alert Summary",
                "critical",
                ["CVE-2026-0001"],
            )

        assert result is True

    def test_http_error_raised(self) -> None:
        """An HTTP error from Slack should be raised."""
        import httpx

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 403
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "forbidden", request=MagicMock(), response=mock_resp,
        )

        with (
            patch("osint_core.workers.notify.httpx.post", return_value=mock_resp),
            pytest.raises(httpx.HTTPStatusError),
        ):
            _post_to_slack(
                "https://hooks.slack.com/services/T/B/X",
                "T", "S", "high", [],
            )

    def test_connection_error_raised(self) -> None:
        """A connection error should be raised."""
        import httpx

        with (
            patch(
                "osint_core.workers.notify.httpx.post",
                side_effect=httpx.ConnectError("unreachable"),
            ),
            pytest.raises(httpx.ConnectError),
        ):
            _post_to_slack(
                "https://hooks.slack.com/services/T/B/X",
                "T", "S", "high", [],
            )


# ---------------------------------------------------------------------------
# Slack integration in send_notification task
# ---------------------------------------------------------------------------


class TestSlackDispatchIntegration:
    """Tests for Slack dispatch within send_notification."""

    def test_slack_only_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When only Slack is configured, it should dispatch via Slack."""
        monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
        monkeypatch.delenv("OSINT_GOTIFY_TOKEN", raising=False)
        monkeypatch.setenv("OSINT_SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        with patch("osint_core.workers.notify._post_to_slack", return_value=True) as mock_slack:
            result = send_notification.run(
                "evt-slack-1",
                {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
            )

        assert result["notified"] is True
        mock_slack.assert_called_once()

    def test_both_channels_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When both Gotify and Slack are configured, both should be called."""
        monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
        monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")
        monkeypatch.setenv("OSINT_SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        with (
            patch("osint_core.workers.notify._post_to_gotify", return_value=True) as mock_gotify,
            patch("osint_core.workers.notify._post_to_slack", return_value=True) as mock_slack,
        ):
            result = send_notification.run(
                "evt-both-1",
                {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
            )

        assert result["notified"] is True
        mock_gotify.assert_called_once()
        mock_slack.assert_called_once()

    def test_gotify_fails_slack_succeeds_no_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If Gotify fails but Slack succeeds, the task should not retry."""
        import httpx

        monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
        monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")
        monkeypatch.setenv("OSINT_SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        with (
            patch(
                "osint_core.workers.notify._post_to_gotify",
                side_effect=httpx.ConnectError("down"),
            ),
            patch("osint_core.workers.notify._post_to_slack", return_value=True),
        ):
            result = send_notification.run(
                "evt-partial-1",
                {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
            )

        # Should still report success because Slack worked.
        assert result["notified"] is True

    def test_all_channels_fail_triggers_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If all configured channels fail, the task should retry."""
        import httpx

        monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
        monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")
        monkeypatch.setenv("OSINT_SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        mock_self = MagicMock()
        mock_self.request.retries = 0
        mock_self.retry.side_effect = Exception("retried")

        with (
            patch(
                "osint_core.workers.notify._post_to_gotify",
                side_effect=httpx.ConnectError("down"),
            ),
            patch(
                "osint_core.workers.notify._post_to_slack",
                side_effect=httpx.ConnectError("also down"),
            ),
            pytest.raises(Exception, match="retried"),
        ):
            send_notification.run.__func__(
                mock_self,
                "evt-allfail-1",
                {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
            )

        mock_self.retry.assert_called_once()

    def test_slack_not_called_when_url_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When OSINT_SLACK_WEBHOOK_URL is not set, Slack should not be called."""
        monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
        monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")
        monkeypatch.delenv("OSINT_SLACK_WEBHOOK_URL", raising=False)

        with (
            patch("osint_core.workers.notify._post_to_gotify", return_value=True),
            patch("osint_core.workers.notify._post_to_slack") as mock_slack,
        ):
            result = send_notification.run(
                "evt-noslack-1",
                {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
            )

        assert result["notified"] is True
        mock_slack.assert_not_called()
