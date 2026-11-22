import hashlib
import math

import pytest

from pericles.core.canonical import canonical_json, digest

pytestmark = pytest.mark.req("REQ-SIM-002")


def test_canonical_json_sorts_keys_and_is_compact() -> None:
    """AC1 (support): equal values serialise to identical bytes."""
    assert canonical_json({"b": 1, "a": [1, 2], "c": {"z": None, "y": True}}) == (
        '{"a":[1,2],"b":1,"c":{"y":true,"z":null}}'
    )


def test_canonical_json_keeps_unicode() -> None:
    assert canonical_json({"name": "Periklés"}) == '{"name":"Periklés"}'


def test_canonical_json_rejects_nan() -> None:
    with pytest.raises(ValueError):
        canonical_json({"x": math.nan})


def test_digest_is_sha256_of_canonical_utf8() -> None:
    value = {"b": "é", "a": 1}
    expected = hashlib.sha256('{"a":1,"b":"é"}'.encode()).hexdigest()
    assert digest(value) == expected
    assert digest({"a": 1, "b": "é"}) == expected
