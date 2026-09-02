"""Composition logging bootstrap: LOG_LEVEL without infrastructure Settings."""

from __future__ import annotations

import logging

import pytest

from composition.logging_config import configure_logging


def test_configure_logging_applies_log_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    root = logging.getLogger()
    previous = root.level
    try:
        configure_logging()
        assert root.level == logging.WARNING
    finally:
        root.setLevel(previous)


def test_configure_logging_defaults_to_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    root = logging.getLogger()
    previous = root.level
    try:
        configure_logging()
        assert root.level == logging.INFO
    finally:
        root.setLevel(previous)


def test_configure_logging_rejects_unknown_level_with_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "NOTALEVEL")
    root = logging.getLogger()
    previous = root.level
    try:
        configure_logging()
        assert root.level == logging.INFO
    finally:
        root.setLevel(previous)
