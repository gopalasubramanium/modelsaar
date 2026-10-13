"""The local classifier's output is untrusted data: it must be exactly one JSON object with the
closed schema {"task": <TASKS>, "confidence": <finite number in [0,1]>}. Anything else is
'malformed' and routing falls back deterministically."""

from __future__ import annotations

import json

import pytest

from modelsaar.routing.classifier import parse_classifier_output
from modelsaar.routing.requirements import TASKS

VALID = [
    ('{"task": "coding", "confidence": 0.9}', ("coding", 0.9)),
    ('  \n{"task": "math", "confidence": 1}\n  ', ("math", 1.0)),
    ('{"confidence": 0, "task": "conversation"}', ("conversation", 0.0)),
    ([{"type": "text", "text": '{"task": "rag", "confidence": 0.5}'}], ("rag", 0.5)),
]

MALFORMED = [
    'Sure! {"task": "coding", "confidence": 0.9}',  # leading prose
    '{"task": "coding", "confidence": 0.9} I hope this helps',  # trailing prose
    '```json\n{"task": "coding", "confidence": 0.9}\n```',  # code fence
    '{"task": "coding", "confidence": 0.9}{"task": "math", "confidence": 0.1}',  # two objects
    '{"task": "coding"}',  # missing key
    '{"task": "coding", "confidence": 0.9, "note": "x"}',  # extra key
    '{"task": "hacking", "confidence": 0.9}',  # not in the closed label set
    '{"task": "coding", "confidence": "0.9"}',  # string confidence
    '{"task": "coding", "confidence": true}',  # bool confidence
    '{"task": "coding", "confidence": 1.5}',  # out of range
    '{"task": "coding", "confidence": -0.1}',
    '{"task": "coding", "confidence": NaN}',
    '{"task": "coding", "confidence": Infinity}',
    '[{"task": "coding", "confidence": 0.9}]',  # array, not object
    '"coding"',
    "",
    "   ",
    None,
    42,
    '{"task": null, "confidence": 0.9}',
    '{"task": ["coding"], "confidence": 0.9}',
]


@pytest.mark.parametrize("content,expected", VALID)
def test_valid_outputs(content, expected):
    task, conf = parse_classifier_output(content)
    assert (task, conf) == expected
    assert task in TASKS and isinstance(conf, float)


@pytest.mark.parametrize("content", MALFORMED)
def test_malformed_outputs_rejected(content):
    with pytest.raises(ValueError):
        parse_classifier_output(content)


def test_every_task_label_accepted():
    for t in TASKS:
        assert parse_classifier_output(json.dumps({"task": t, "confidence": 0.5}))[0] == t


def test_classify_reports_malformed_and_falls_back():
    """End to end through LocalClassifier.classify with a stub adapter returning prose."""
    import asyncio

    from modelsaar.adapters.base import UpstreamResponse
    from modelsaar.config import ClassifierConfig
    from modelsaar.routing.classifier import LocalClassifier
    from modelsaar.routing.requirements import Requirements

    class Dep:
        def cap(self, k):
            return "unknown"

    class Adapter:
        def __init__(self, content):
            self.content = content

        async def chat(self, dep, body, stream, timeout):
            return UpstreamResponse(status=200, headers={}, body={"choices": [{"message": {"content": self.content}}]}, elapsed_ms=1.0)

    clf = LocalClassifier(ClassifierConfig(enabled=True, backend="b", model="m"))
    req = Requirements()
    out = asyncio.run(clf.classify(Adapter('Here you go: {"task": "coding", "confidence": 0.9}'), Dep(), {"messages": []}, req))
    assert out.used is False and out.status == "malformed"
    out = asyncio.run(clf.classify(Adapter('{"task": "coding", "confidence": 0.9}'), Dep(), {"messages": []}, req))
    assert out.used is True and out.status == "ok" and out.task == "coding" and out.confidence == 0.9
