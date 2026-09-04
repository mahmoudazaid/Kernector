"""Unit tests for HTTP adapter helpers."""

import pytest

from presentation.http.app import _json_pointer


@pytest.mark.parametrize(
    ("loc", "expected"),
    [
        ((), "#"),
        (("body",), "#"),
        (("body", "field"), "#/field"),
        (("body", "body"), "#/body"),
        (("query", "limit"), "#/limit"),
        (("body", "a/b", "c~d"), "#/a~1b/c~0d"),
    ],
)
def test_json_pointer(loc: tuple[object, ...], expected: str) -> None:
    assert _json_pointer(loc) == expected
