"""One bounded R1 caller check: evaluate --probe must retain uncertainty across deployments."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from conftest import build_gateway, make_models
from test_correction_2026_10_12 import ContinuingBackend

from modelsaar.config import AdmissionConfig, BackendConfig, ResourcePool
from modelsaar.evaluation.harness import probe_all


@pytest.mark.parametrize("times_out", [True, False], ids=["uncertain-cross-deployment-regression", "completed-probes-control"])
def test_r1_evaluation_probes_respect_shared_pool_after_timeout(times_out):
    # The actual backend timeout is the meaningful short deadline. probe_all's120s
    # argument is bounded by the corrected adapter's min(server, backend) rule.
    fake = ContinuingBackend(make_models()[:2], duration=0.5 if times_out else 0.005)
    fake.start()
    g = build_gateway(
        f"http://127.0.0.1:{fake.port}",
        backends=(BackendConfig(id="ollama", type="ollama", base_url=f"http://127.0.0.1:{fake.port}",
                                resource_pool="pool", timeout_s=0.08),),
        resource_pools=(ResourcePool(id="pool", max_concurrent=1, max_queue=0),),
        admission=AdmissionConfig(uncertain_hold_s=1.0, max_queue=0),
    )
    try:
        eligible = [d for d in g.router.registry.all()
                    if d.role == "generative" and d.healthy and d.locality == "local"]
        assert len(eligible) == 2, "fixture must offer two eligible deployments before probing"
        results = probe_all(g.gw)
        admission = g.admin.get("/admin/status").json()["admission"]["pool:pool"]
        observation = {
            "case": "r1_eval_probe_all", "times_out": times_out,
            "eligible_before_probe": [d.id for d in eligible],
            "configured_pool_concurrency": 1, "configured_backend_timeout_s": 0.08,
            "backend_max_active": fake.max_active, "backend_active_after_probes": fake.active,
            "backend_requests": fake.requests, "admission": admission,
            "probe_results": [{"deployment": r["deployment_id"], "uncertain": r["uncertain"],
                               "skipped": r["skipped"]} for r in results],
        }
        Path(__file__).with_name("probe-timeout.json" if times_out else "probe-completed-control.json").write_text(json.dumps(observation, indent=2) + "\n")
        print("OBSERVATION " + json.dumps(observation, sort_keys=True))
        assert fake.max_active <= 1, "evaluation probe_all started a second deployment while the timed-out first deployment still computed in the same one-slot pool"
        if times_out:
            # A valid correction may stop/defer the next deployment, or wait for
            # recovery and then continue. It must not be forced to dispatch both.
            assert fake.requests and any(r.get("uncertain") for r in results)
            if fake.active > 0:
                assert admission["uncertain"] == 1, "evaluation probe caller discarded uncertainty while backend work remains active"
        else:
            assert len(results) == 2 and {r["model"] for r in fake.requests} == {d.model for d in eligible}
            assert all(not r["uncertain"] for r in results)
    finally:
        time.sleep(0.6 if times_out else 0.02)
        g.gw.stop()
        fake.stop()
