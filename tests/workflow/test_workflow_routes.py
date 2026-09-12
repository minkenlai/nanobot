"""Tests for workflow HTTP/WS routes and cron synchronization."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request as WsRequest

from nanobot.cron.service import CronService
from nanobot.workflow.schema import (
    PassState,
    TriggerConfig,
    WorkflowDefinition,
)
from nanobot.workflow.service import WorkflowService


def test_cron_sync(tmp_path: Path) -> None:
    cron_store = tmp_path / "cron" / "jobs.json"
    cron = CronService(cron_store)
    service = WorkflowService(tmp_path / "workflows", cron_service=cron)

    wf = WorkflowDefinition(
        id="daily_triage",
        name="Daily Triage",
        trigger=TriggerConfig(cron="0 9 * * *", tz="UTC", enabled=True),
        start_at="Step1",
        states={"Step1": PassState(type="pass", end=True)},
    )
    service.save_workflow(wf)

    # Verify cron job was registered
    job = cron.get_job("workflow:daily_triage")
    assert job is not None
    assert job.name == "Workflow: Daily Triage"
    assert job.schedule.expr == "0 9 * * *"
    assert job.payload.kind == "workflow"
    assert job.payload.workflow_id == "daily_triage"

    # Disable trigger and sync
    wf.trigger = TriggerConfig(cron="0 9 * * *", enabled=False)
    service.save_workflow(wf)
    assert cron.get_job("workflow:daily_triage") is None

    # Re-enable, then delete
    wf.trigger = TriggerConfig(cron="0 9 * * *", enabled=True)
    service.save_workflow(wf)
    assert cron.get_job("workflow:daily_triage") is not None

    service.delete_workflow("daily_triage")
    assert cron.get_job("workflow:daily_triage") is None


def _make_req(path: str, mutation_payload: dict | None = None) -> WsRequest:
    req = WsRequest(path, Headers())
    setattr(req, "_nanobot_trusted_proxy_authenticated", True)
    if mutation_payload is not None:
        setattr(req, "_nanobot_webui_mutation_payload", mutation_payload)
    return req


@pytest.mark.asyncio
async def test_workflow_routes_crud_and_run(tmp_path: Path) -> None:
    from nanobot.channels.websocket.runtime import WebSocketConfig
    from nanobot.webui.gateway_services import build_gateway_services

    cfg = WebSocketConfig.model_validate({
        "enabled": True,
        "allowFrom": ["*"],
        "host": "127.0.0.1",
        "port": 8765,
        "path": "/",
        "websocketRequiresToken": False,
    })
    bus = MagicMock()
    cron_store = tmp_path / "cron" / "jobs.json"
    cron = CronService(cron_store)
    wf_service = WorkflowService(tmp_path / "workflows", cron_service=cron)

    services = build_gateway_services(
        config=cfg,
        bus=bus,
        session_manager=None,
        static_dist_path=None,
        workspace_path=tmp_path,
        default_restrict_to_workspace=False,
        runtime_model_name=None,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
        cron_service=cron,
        workflow_service=wf_service,
    )
    http = services.http

    # 1. List (initially empty)
    req = _make_req("/api/webui/workflows")
    res = await http._dispatch_workflow_routes(req, "/api/webui/workflows")
    assert res is not None
    assert res.status_code == 200
    data = json.loads(res.body.decode("utf-8"))
    assert data["workflows"] == []

    # 2. Save via mutation payload
    wf_def = {
        "id": "test_wf",
        "name": "Test Workflow",
        "start_at": "Start",
        "states": {
            "Start": {
                "type": "pass",
                "result": {"status": "ready"},
                "result_path": "$.test_result",
                "end": True,
            }
        },
    }
    req_save = _make_req("/api/webui/workflows/save", {"definition": wf_def})
    res_save = await http._dispatch_workflow_routes(req_save, "/api/webui/workflows/save")
    assert res_save is not None
    assert res_save.status_code == 200
    save_data = json.loads(res_save.body.decode("utf-8"))
    assert save_data["status"] == "ok"
    assert save_data["workflow"]["id"] == "test_wf"

    # 3. Get workflow by ID
    req_get = _make_req("/api/webui/workflows/test_wf")
    res_get = await http._dispatch_workflow_routes(req_get, "/api/webui/workflows/test_wf")
    assert res_get is not None
    assert res_get.status_code == 200
    get_data = json.loads(res_get.body.decode("utf-8"))
    assert get_data["name"] == "Test Workflow"

    # 4. Run workflow
    req_run = _make_req("/api/webui/workflows/run", {"id": "test_wf", "initial_context": {"user": "alice"}})
    res_run = await http._dispatch_workflow_routes(req_run, "/api/webui/workflows/run")
    assert res_run is not None
    assert res_run.status_code == 200
    run_data = json.loads(res_run.body.decode("utf-8"))
    assert run_data["status"] == "ok"
    run_record = run_data["run"]
    assert run_record["workflow_id"] == "test_wf"
    assert run_record["status"] == "succeeded"
    assert run_record["final_context"]["test_result"]["status"] == "ready"
    run_id = run_record["run_id"]

    # 5. List runs
    req_runs = _make_req("/api/webui/workflows/test_wf/runs")
    res_runs = await http._dispatch_workflow_routes(req_runs, "/api/webui/workflows/test_wf/runs")
    assert res_runs is not None
    assert res_runs.status_code == 200
    runs_data = json.loads(res_runs.body.decode("utf-8"))
    assert len(runs_data["runs"]) == 1
    assert runs_data["runs"][0]["run_id"] == run_id

    # 6. Run detail
    req_run_detail = _make_req(f"/api/webui/workflows/test_wf/runs/{run_id}")
    res_run_detail = await http._dispatch_workflow_routes(req_run_detail, f"/api/webui/workflows/test_wf/runs/{run_id}")
    assert res_run_detail is not None
    assert res_run_detail.status_code == 200
    detail_data = json.loads(res_run_detail.body.decode("utf-8"))
    assert detail_data["run_id"] == run_id

    # 7. Delete workflow
    req_del = _make_req("/api/webui/workflows/delete", {"id": "test_wf"})
    res_del = await http._dispatch_workflow_routes(req_del, "/api/webui/workflows/delete")
    assert res_del is not None
    assert res_del.status_code == 200

    # Verify deleted
    res_get_del = await http._dispatch_workflow_routes(req_get, "/api/webui/workflows/test_wf")
    assert res_get_del is not None
    assert res_get_del.status_code == 404


@pytest.mark.asyncio
async def test_workflow_routes_disabled_config(tmp_path: Path) -> None:
    from nanobot.channels.websocket.runtime import WebSocketConfig
    from nanobot.webui.gateway_services import build_gateway_services

    cfg = WebSocketConfig.model_validate({
        "enabled": True,
        "allowFrom": ["*"],
        "host": "127.0.0.1",
        "port": 8765,
        "path": "/",
        "websocketRequiresToken": False,
    })
    bus = MagicMock()

    services = build_gateway_services(
        config=cfg,
        bus=bus,
        session_manager=None,
        static_dist_path=None,
        workspace_path=tmp_path,
        default_restrict_to_workspace=False,
        runtime_model_name=None,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
        cron_service=None,
        workflow_service=None,
    )
    http = services.http
    assert http.workflow_service is None

    # Test that route dispatch returns 404 with disabled message
    req = _make_req("/api/webui/workflows")
    res = await http._dispatch_workflow_routes(req, "/api/webui/workflows")
    assert res is not None
    assert res.status_code == 404
    assert b"disabled" in res.body.lower()


