"""Shared pytest configuration and fixtures for DRI tests."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so pytest doesn't warn about unknown marks."""
    config.addinivalue_line(
        "markers",
        "sqlite_only: marks tests that are specific to the SQLite backend "
        "and must not run against TimescaleDB or other backends.",
    )
    config.addinivalue_line(
        "markers",
        "timescale: marks integration tests that require a live TimescaleDB "
        "instance (skipped unless TIMESCALE_TEST_URL env var is set).",
    )
