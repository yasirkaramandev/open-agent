import importlib.util
import sys
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parents[2] / "apps/worker/worker.py"
spec = importlib.util.spec_from_file_location("signal_worker", WORKER)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_background_engagement_is_not_in_worker_allowlist() -> None:
    assert all(
        "comment" not in task and "like" not in task and "subscribe" not in task
        for task in module.AUTOMATIC_TASKS
    )
    with pytest.raises(PermissionError, match="background_engagement_blocked"):
        module.enqueue_automatic("comment")


def test_write_execution_requires_complete_approval_evidence() -> None:
    envelope = module.ExecutionEnvelope(
        proposal_id="proposal_1",
        account_id="account_1",
        approval_hash="",
        idempotency_key="idem_1",
        feature_flag_enabled=False,
    )
    with pytest.raises(PermissionError, match="approval_evidence_incomplete"):
        module.execute_youtube_write(envelope)
