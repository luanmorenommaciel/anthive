"""Smoke test — verifies the package imports cleanly.

Real tests per module land during p0-p5 implementation.
"""

import anthive


def test_version_present() -> None:
    assert anthive.__version__ == "0.0.1"


def test_cli_imports() -> None:
    from anthive.cli import app  # noqa: F401
