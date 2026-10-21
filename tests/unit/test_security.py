"""測試目標：app.core.security.safe_next_path（防 open redirect）"""

import pytest

from app.core.security import safe_next_path


@pytest.mark.parametrize(
    ("next_path", "expected"),
    [
        ("/invoices", "/invoices"),
        ("/invoices?page=2", "/invoices?page=2"),
        (None, "/"),
        ("", "/"),
        ("https://evil.example.com", "/"),
        ("//evil.example.com", "/"),
        ("/\\evil.example.com", "/"),
    ],
)
def test_safe_next_path(next_path: str | None, expected: str) -> None:
    assert safe_next_path(next_path) == expected
