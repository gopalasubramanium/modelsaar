"""Bounded R7 closure checks: a routed result depends on its eligible alternatives.

Uses the production format-2 writer/reuse path with a fake HTTP transport. All
keys, fingerprints and responses are synthetic; no real model is contacted.
"""
from __future__ import annotations

import json

import httpx
import pytest

from modelsaar.evaluation.harness import EvalRun


TASK = {"id": "eligible-set-check", "category": "conversation", "split": "test",
        "messages": [{"role": "user", "content": "A synthetic unchanged task"}],
        "expected": {"type": "contains", "value": "ok"}}


def attach_transport(run, deployment, requests):
    run.c.close()

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
                              headers={"x-modelsaar-deployment": deployment,
                                       "x-modelsaar-request-id": "synthetic-review-request"})

    run.c = httpx.Client(base_url="http://127.0.0.1:9", transport=httpx.MockTransport(respond))


@pytest.mark.parametrize("change,policy,expected_requests", [
    ("add_candidate", "auto", 1),
    ("change_alternative_identity", "auto", 1),
    ("unchanged", "auto", 0),
    ("add_candidate", "test:local/a", 0),
], ids=["added-candidate-regression", "alternative-identity-regression", "unchanged-resume-control", "fixed-sweep-control"])
def test_resume_tracks_eligible_alternatives(tmp_path, change, policy, expected_requests):
    checkpoint = tmp_path / "checkpoint.jsonl"
    model = "auto" if policy == "auto" else "local/a"
    initial = {"local/a": "identity-a", "local/b": "identity-b"}
    first = EvalRun("http://127.0.0.1:9", "fake-key", "fake-admin", simulated=False, checkpoint=checkpoint)
    first.fingerprints = initial.copy()
    first.routing_config_hash = "unchanged-config-file"
    original_requests = []
    attach_transport(first, "local/a", original_requests)
    try:
        original = first.run_one(TASK, model, policy)
        assert original["ok"] and len(original_requests) == 1
        assert original["checkpoint_format"] == 2
    finally:
        first.c.close()
        first.admin.close()

    updated = initial.copy()
    if change == "add_candidate":
        updated["local/c"] = "identity-c"
    elif change == "change_alternative_identity":
        updated["local/b"] = "identity-b-replaced"
    resumed = EvalRun("http://127.0.0.1:10", "fake-key", "fake-admin", simulated=False,
                      checkpoint=checkpoint, resume=True)
    resumed.fingerprints = updated
    resumed.routing_config_hash = "unchanged-config-file"
    requests = []
    attach_transport(resumed, "local/c" if change == "add_candidate" else "local/b", requests)
    try:
        result = resumed.run_one(TASK, model, policy)
        print(json.dumps({"case": change, "policy": policy, "old_eligible": initial,
                          "new_eligible": updated, "requests_sent": len(requests),
                          "resumed": result.get("resumed", False), "deployment": result.get("deployment"),
                          "resume_rejected": resumed.resume_rejected}, sort_keys=True))
        assert len(requests) == expected_requests, "routed format-2 checkpoint ignored changed eligible alternative identities"
    finally:
        resumed.c.close()
        resumed.admin.close()
