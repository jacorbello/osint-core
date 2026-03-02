"""Tests for structured logging configuration."""

import json

import structlog

from osint_core.logging import configure_logging


def test_structlog_produces_json(capsys):
    configure_logging(log_level="INFO")
    logger = structlog.get_logger()
    logger.info("test_event", key="value")
    captured = capsys.readouterr()
    # Output should be valid JSON
    line = captured.out.strip().split("\n")[-1]
    parsed = json.loads(line)
    assert parsed["event"] == "test_event"
    assert parsed["key"] == "value"
    assert "level" in parsed


def test_structlog_includes_timestamp(capsys):
    configure_logging(log_level="INFO")
    logger = structlog.get_logger()
    logger.info("ts_event")
    captured = capsys.readouterr()
    line = captured.out.strip().split("\n")[-1]
    parsed = json.loads(line)
    assert "timestamp" in parsed


def test_structlog_filters_below_level(capsys):
    configure_logging(log_level="WARNING")
    logger = structlog.get_logger()
    logger.info("should_be_filtered")
    captured = capsys.readouterr()
    assert captured.out.strip() == ""


def test_structlog_passes_at_or_above_level(capsys):
    configure_logging(log_level="WARNING")
    logger = structlog.get_logger()
    logger.warning("should_appear")
    captured = capsys.readouterr()
    line = captured.out.strip().split("\n")[-1]
    parsed = json.loads(line)
    assert parsed["event"] == "should_appear"
    assert parsed["level"] == "warning"
