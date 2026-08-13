from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reliable_agent_runtime.api.app import create_app
from reliable_agent_runtime.settings import Settings


def test_action_api_supports_incremental_planning_and_idempotent_replay(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'actions.db'}"),
    )
    payload = {
        "objective": "Inspect the current order before deciding what to do next.",
        "actor": "adaptive-agent",
        "action_id": "read_order",
        "tool": "retail.get_order",
        "arguments": {"order_id": "ord-1001"},
    }

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/actions",
            json=payload,
            headers={"Idempotency-Key": "session-1:read-order"},
        )
        replay = client.post(
            "/api/v1/actions",
            json=payload,
            headers={"Idempotency-Key": "session-1:read-order"},
        )

    assert created.status_code == 201
    assert created.json()["status"] == "succeeded"
    assert created.json()["result"]["order_id"] == "ord-1001"
    assert created.json()["plan"]["steps"][0]["id"] == "read_order"
    assert replay.status_code == 200
    assert replay.json()["id"] == created.json()["id"]


def test_action_api_surfaces_approval_then_reuses_existing_run(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=Settings(
            database_url=f"sqlite+pysqlite:///{tmp_path / 'approval-action.db'}",
            demo_refund_unknown_outcome_once=True,
        ),
    )
    payload = {
        "objective": "Refund an eligible order after approval.",
        "actor": "adaptive-agent",
        "action_id": "refund_order",
        "tool": "retail.issue_refund",
        "arguments": {"order_id": "ord-1001", "amount_cents": 12900},
    }

    with TestClient(app) as client:
        waiting = client.post(
            "/api/v1/actions",
            json=payload,
            headers={"Idempotency-Key": "session-2:refund-order"},
        )
        run_id = waiting.json()["id"]
        approvals = client.get(f"/api/v1/runs/{run_id}/approvals").json()
        approval_id = approvals[0]["id"]
        client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={
                "decision": "approve",
                "actor": "manager",
                "reason": "order and policy verified",
            },
        )
        completed = client.post(f"/api/v1/runs/{run_id}/execute")
        replay = client.post(
            "/api/v1/actions",
            json=payload,
            headers={"Idempotency-Key": "session-2:refund-order"},
        )
        events = client.get(f"/api/v1/runs/{run_id}/events").json()

    assert waiting.status_code == 201
    assert waiting.json()["status"] == "waiting_approval"
    assert completed.status_code == 200
    assert completed.json()["status"] == "succeeded"
    assert completed.json()["result"]["status"] == "succeeded"
    assert replay.status_code == 200
    assert replay.json()["id"] == run_id
    assert sum(event["type"] == "tool.outcome_recovered" for event in events) == 1


def test_action_idempotency_rejects_same_key_with_different_payload(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'conflict.db'}"),
    )
    first_payload = {
        "objective": "Read an order.",
        "actor": "adaptive-agent",
        "action_id": "read_order",
        "tool": "retail.get_order",
        "arguments": {"order_id": "ord-1001"},
    }
    changed_payload = {
        **first_payload,
        "arguments": {"order_id": "ord-missing"},
    }

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/actions",
            json=first_payload,
            headers={"Idempotency-Key": "same-action-key"},
        )
        conflict = client.post(
            "/api/v1/actions",
            json=changed_payload,
            headers={"Idempotency-Key": "same-action-key"},
        )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
