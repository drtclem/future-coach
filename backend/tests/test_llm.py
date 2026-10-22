import json

import pytest

from app.llm import _parse_json


def test_parse_json_repairs_the_small_tier_failure_modes():
    assert _parse_json('{"a": 1}') == ({"a": 1}, False)
    data, repaired = _parse_json('Here you go: {"items": [{"cue": "she said "go" today"},], "summary": "x"}')
    assert repaired and data["summary"] == "x" and len(data["items"]) == 1
    with pytest.raises(json.JSONDecodeError):
        _parse_json("")  # nothing to repair: still a model failure, so the caller falls back
