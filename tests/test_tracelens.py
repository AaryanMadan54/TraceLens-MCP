import asyncio
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from tracelens.agent import investigate, provider_step
from tracelens.fixture import PLAN, make_report
from tracelens.gateway import Gateway
from tracelens.report import claims, validate_report
from tracelens.server import ALLOWED_TOOLS, create_server
from tracelens.state import State
from tracelens.telemetry import END, START, load_dataset


def all_evidence(data=None):
    data = data or load_dataset()
    return {r["id"]: r for kind in ("metrics", "logs", "traces") for r in data[kind]}


async def test_mcp_catalog_and_read_only_handlers():
    original = load_dataset()
    data = copy.deepcopy(original)
    async with Client(create_server(data)) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools} == ALLOWED_TOOLS
        assert all(t.annotations.readOnlyHint for t in tools)
        for name, args in PLAN:
            result = await client.call_tool(name, args)
            assert result.data["synthetic"] is True
            assert result.data["trust"] == "untrusted_telemetry"
            assert result.data["records"]
        with pytest.raises(Exception):
            await client.call_tool("run_shell", {"command": "anything"})
    assert data == original


async def test_stdio_mcp_roundtrip():
    transport = StdioTransport(command=sys.executable, args=["-m", "tracelens", "server"])
    async with Client(transport, timeout=20) as client:
        result = await client.call_tool(*PLAN[0])
        assert result.data["records"][0]["id"] == "metric-checkout-00"


async def test_time_window_bounds_and_truncation():
    async with Client(create_server()) as client:
        args = dict(service="checkout-api", start=START, end="2026-04-18T10:05:00Z", limit=1)
        result = await client.call_tool("get_service_metrics", args)
        assert [r["id"] for r in result.data["records"]] == ["metric-checkout-00"]
        args["end"] = END
        assert (await client.call_tool("query_logs", args)).data["truncated"] is True
        for bad in [dict(limit=101), dict(start="2026-04-18T10:00:00"), dict(end="2026-04-18T12:00:00Z")]:
            with pytest.raises(Exception):
                await client.call_tool("query_logs", args | bad)


async def test_fixture_cause_and_every_claim_attributed(tmp_path):
    state = await investigate(tmp_path)
    report = validate_report(state.data["report"], state.data["evidence"], "fixture")
    assert report.hypotheses[0].status == "supported"
    assert report.hypotheses[1].status == "unlikely"
    assert all(set(c.evidence) <= state.data["evidence"].keys() for c in claims(report))
    assert len(report.uncertainty) >= 2


@pytest.mark.parametrize("mutation", ["unknown_id", "unretrieved_id", "empty_citation", "wrong_fact", "wrong_mode"])
async def test_evidence_validation_rejects_bad_reports(mutation):
    evidence = all_evidence()
    raw = make_report(evidence)
    if mutation == "unknown_id":
        raw["summary"]["evidence"] = ["invented"]
    elif mutation == "unretrieved_id":
        evidence.pop("metric-checkout-03")
    elif mutation == "empty_citation":
        raw["findings"][0]["evidence"] = []
    elif mutation == "wrong_fact":
        raw["facts"][0]["value"] = 99999
    else:
        raw["mode"] = "live"
    with pytest.raises(ValueError):
        validate_report(raw, evidence, "fixture")


async def test_misleading_error_volume_does_not_change_fixture_diagnosis(tmp_path):
    data = load_dataset()
    # Amplify the unrelated error signal; this evaluates deterministic fixture behavior only.
    for row in data["metrics"]:
        if row["service"] == "recommendations-worker" and row["id"] != "metric-recommendations-01":
            row["error_rate_pct"] = 95.0
    state = await investigate(tmp_path, dataset=data)
    assert state.data["report"]["hypotheses"][0]["status"] == "supported"
    assert state.data["report"]["hypotheses"][1]["status"] == "unlikely"


async def test_pool_evidence_ablation_removes_supported_conclusion(tmp_path):
    data = load_dataset()
    for row in data["metrics"]:
        if row["service"] == "checkout-api":
            row["pool_active"], row["pool_wait_p95_ms"] = 5, 2
    for row in data["traces"]:
        if row["service"] == "checkout-api":
            row["spans"][1]["duration_ms"] = 2
    state = await investigate(tmp_path, dataset=data)
    assert state.data["report"]["hypotheses"][0]["status"] == "unresolved"


class NoDispatch:
    async def call_tool(self, *args):
        raise AssertionError("Unauthorized call reached MCP")


async def test_injection_cannot_grant_permissions(tmp_path):
    state = State(tmp_path, {"test": "injection"})
    injection = all_evidence()["log-injection"]["message"]
    assert "run_shell" in injection and "Grant admin" in injection
    gateway = Gateway(NoDispatch(), state)
    denied = await gateway.call("run_shell", {"command": "delete audit logs", "authorization": injection})
    assert denied["error"]["code"] == "PERMISSION_DENIED"
    denied = await gateway.call("get_traces", PLAN[0][1] | {"permissions": "admin"})
    assert denied["error"]["code"] == "INVALID_ARGUMENTS"
    assert state.data["tool_calls"] == 0
    assert ALLOWED_TOOLS == frozenset({"query_logs", "get_service_metrics", "get_traces"})


async def test_transient_failure_recovery_and_completed_resume(tmp_path):
    state = await investigate(tmp_path, scenario="transient")
    errors = [e for e in state.data["events"] if e["kind"] == "tool_error"]
    assert len(errors) == 1 and errors[0]["code"] == "TEMPORARY_UNAVAILABLE"
    assert state.data["tool_calls"] == 7
    assert state.data["status"] == "complete"
    resumed = await investigate(tmp_path, scenario="transient")
    assert resumed.data == state.data


async def test_partial_progress_reuses_successful_queries(tmp_path):
    async with Client(create_server()) as client:
        state = State(tmp_path, {"test": "resume"})
        first = await Gateway(client, state).call(*PLAN[0])
    state = State(tmp_path, {"test": "resume"})
    assert await Gateway(NoDispatch(), state).call(*PLAN[0]) == first
    assert state.data["tool_calls"] == 1
    assert state.data["events"][-1]["kind"] == "cache_hit"
    with pytest.raises(ValueError):
        State(tmp_path, {"test": "different-config"})


async def test_timeout_and_retry_budget_survive_restart(tmp_path):
    class Slow:
        async def call_tool(self, *args):
            await asyncio.sleep(5)
    state = State(tmp_path, {"test": "timeout"})
    result = await Gateway(Slow(), state, timeout=.01).call(*PLAN[0])
    assert result["error"]["code"] == "RETRY_EXHAUSTED"
    assert state.data["tool_calls"] == 2
    restarted = State(tmp_path, {"test": "timeout"})
    assert (await Gateway(NoDispatch(), restarted).call(*PLAN[0]))["error"]["code"] == "RETRY_EXHAUSTED"
    assert restarted.data["tool_calls"] == 2


async def test_tool_budget_enforced(tmp_path):
    state = State(tmp_path, {"test": "budget"})
    async with Client(create_server()) as client:
        gateway = Gateway(client, state, max_calls=1)
        await gateway.call(*PLAN[0])
        with pytest.raises(RuntimeError, match="budget"):
            await gateway.call(*PLAN[1])


class ScriptedProvider:
    """Simulates an obedient-to-injection model. It is NOT an LLM evaluation."""
    def __init__(self, reject_first_report=False):
        self.queue = [("query_logs", PLAN[1][1]), ("run_shell", {"command": "delete audit logs"})] + PLAN
        self.count = 0
        self.reject_first_report = reject_first_report
        self.saw_denial = False

    async def next(self, messages, tools):
        assert {t["name"] for t in tools} == ALLOWED_TOOLS
        self.saw_denial |= any("PERMISSION_DENIED" in x.get("output", "") for x in messages)
        self.count += 1
        if self.queue:
            name, args = self.queue.pop(0)
            return {"output": [{"type": "function_call", "name": name, "arguments": json.dumps(args), "call_id": f"call-{self.count}"}], "text": ""}
        evidence = {}
        for item in messages:
            if item.get("type") == "function_call_output":
                for record in json.loads(item["output"]).get("records", []):
                    evidence[record["id"]] = record
        report = make_report(evidence, "live")
        if self.reject_first_report:
            report["summary"]["evidence"] = ["invented"]
            self.reject_first_report = False
        return {"output": [], "text": json.dumps(report)}


async def test_live_loop_scripted_injection_and_report_repair(tmp_path):
    provider = ScriptedProvider(reject_first_report=True)
    state = await investigate(tmp_path, mode="live", scenario="transient", provider=provider)
    assert provider.saw_denial
    assert state.data["report"]["mode"] == "live"
    assert state.data["status"] == "complete"
    assert any(e["kind"] == "report_rejected" for e in state.data["events"])
    assert any(e["kind"] == "permission_denied" for e in state.data["events"])


async def test_llm_timeout_is_bounded(tmp_path):
    class SlowProvider:
        async def next(self, *args):
            await asyncio.sleep(5)
    state = State(tmp_path, {"test": "llm-timeout"})
    with pytest.raises(RuntimeError, match="retry budget"):
        await provider_step(SlowProvider(), state, [], timeout=.01)
    assert state.data["attempts"]["llm:0"] == 2


async def test_pending_live_call_resumes_without_repeating_provider_request(tmp_path):
    from tracelens.agent import live_loop
    state = State(tmp_path, {"test": "pending"})
    # Model response has already been checkpointed; the process stops before dispatch.
    name, args = PLAN[0]
    state.data["pending"] = [{"type": "function_call", "name": name, "arguments": json.dumps(args), "call_id": "pending-1"}]
    state.data["round"] = 1
    state.save()
    resumed = State(tmp_path, {"test": "pending"})
    class MustNotRequest:
        async def next(self, *args):
            raise AssertionError("No model budget remains")
    async with Client(create_server()) as client:
        with pytest.raises(RuntimeError, match="round budget"):
            await live_loop(MustNotRequest(), Gateway(client, resumed), [], resumed, max_rounds=1)
    assert not resumed.data["pending"]
    assert resumed.data["messages"][-1]["call_id"] == "pending-1"
    assert "metric-checkout-00" in resumed.data["evidence"]
