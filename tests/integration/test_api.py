from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from reliable_agent_runtime.api.app import create_app
from reliable_agent_runtime.settings import Settings
from tests.helpers import refund_api_payload


def test_full_api_flow_and_idempotent_create(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'api.db'}"),
    )
    payload = refund_api_payload()

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/runs",
            json=payload,
            headers={"Idempotency-Key": "api-demo"},
        )
        assert created.status_code == 201
        run_id = created.json()["id"]
        assert created.headers["location"] == f"/api/v1/runs/{run_id}"
        assert created.headers["etag"] == 'W/"1"'

        replay = client.post(
            "/api/v1/runs",
            json=payload,
            headers={"Idempotency-Key": "api-demo"},
        )
        assert replay.status_code == 200
        assert replay.json()["id"] == run_id

        waiting = client.post(f"/api/v1/runs/{run_id}/execute")
        assert waiting.status_code == 200
        assert waiting.json()["status"] == "waiting_approval"
        assert "etag" in waiting.headers
        assert "location" not in waiting.headers

        approvals = client.get(f"/api/v1/runs/{run_id}/approvals")
        approval_id = approvals.json()[0]["id"]
        decided = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": "approve", "actor": "manager", "reason": "approved"},
        )
        assert decided.status_code == 200
        assert decided.json()["status"] == "approved"

        completed = client.post(f"/api/v1/runs/{run_id}/execute")
        assert completed.status_code == 200
        assert completed.json()["status"] == "succeeded"

        events = client.get(f"/api/v1/runs/{run_id}/events")
        sequences = [event["sequence"] for event in events.json()]
        assert sequences == sorted(sequences)
        assert len(sequences) == len(set(sequences))


def test_errors_use_rfc_9457_problem_details(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'errors.db'}"),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/runs/run_missing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "run_not_found"
    assert body["status"] == 404
    assert body["type"].startswith("urn:reliable-agent-runtime:problem:")
    assert body["request_id"].startswith("req_")


def test_optional_api_key_is_enforced(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            database_url=f"sqlite+pysqlite:///{tmp_path / 'auth.db'}",
            api_key="secret-key",
        ),
    )

    with TestClient(app) as client:
        unauthorized = client.get("/api/v1/tools")
        authorized = client.get("/api/v1/tools", headers={"X-API-Key": "secret-key"})
        live = client.get("/health/live")

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert live.status_code == 200


def test_create_idempotency_conflict_is_exposed_as_problem_detail(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'conflict.db'}"),
    )
    payload = refund_api_payload()

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/runs",
            json=payload,
            headers={"Idempotency-Key": "same-key"},
        )
        changed = {**payload, "objective": "A different objective."}
        conflict = client.post(
            "/api/v1/runs",
            json=changed,
            headers={"Idempotency-Key": "same-key"},
        )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.headers["content-type"].startswith("application/problem+json")
    assert conflict.json()["code"] == "idempotency_conflict"


def test_approval_decision_is_one_time(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'approval.db'}"),
    )

    with TestClient(app) as client:
        created = client.post("/api/v1/runs", json=refund_api_payload())
        run_id = created.json()["id"]
        client.post(f"/api/v1/runs/{run_id}/execute")
        approval_id = client.get(f"/api/v1/runs/{run_id}/approvals").json()[0]["id"]
        first = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": "approve", "actor": "manager", "reason": "approved"},
        )
        duplicate = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": "approve", "actor": "manager", "reason": "approved"},
        )

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "approval_already_decided"


def test_api_rejects_unknown_fields_and_echoes_request_id(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'strict.db'}"),
    )
    payload = {**refund_api_payload(), "unexpected": "not allowed"}

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs",
            json=payload,
            headers={"X-Request-ID": "req_client_supplied"},
        )

    assert response.status_code == 422
    assert response.headers["x-request-id"] == "req_client_supplied"
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "request_validation_error"
    assert body["request_id"] == "req_client_supplied"
    assert any(error["type"] == "extra_forbidden" for error in body["errors"])


def test_tool_discovery_exposes_side_effect_and_json_schema(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'tools.db'}"),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/tools")

    assert response.status_code == 200
    by_name = {tool["name"]: tool for tool in response.json()}
    refund = by_name["retail.issue_refund"]
    assert refund["effect"] == "irreversible"
    assert refund["idempotent"] is True
    assert refund["input_schema"]["additionalProperties"] is False
    assert "amount_cents" in refund["input_schema"]["properties"]


def test_openapi_documents_problem_json_and_resource_headers(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'openapi.db'}"),
    )
    schema = app.openapi()

    create_run = schema["paths"]["/api/v1/runs"]["post"]
    validation_content = create_run["responses"]["422"]["content"]
    assert "application/problem+json" in validation_content

    run_schema = schema["components"]["schemas"]["RunResponse"]
    assert "version" in run_schema["properties"]
    assert schema["openapi"].startswith("3.1")
