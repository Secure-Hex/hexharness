"""The declarative workflow engine: ordering, templating, for_each, condition,
output binding, and stop-on-failure. Uses a fake step_runner (no control plane)."""
from __future__ import annotations

from hexharness.agent.workflow import RunWorkflowInput, run_workflow


def _recorder(script=None):
    """A fake step_runner that records calls and returns canned outputs by tool name."""
    calls = []
    script = script or {}

    async def runner(tool: str, inp: dict):
        calls.append((tool, inp))
        result = script.get(tool, "ok")
        return (result != "FAIL", "" if result == "FAIL" else result)

    return runner, calls


async def test_sequential_templating_passes_outputs() -> None:
    runner, calls = _recorder({"port_scan": "22\n80", "http_probe": "200"})
    data = RunWorkflowInput(
        variables={"target": "app.test"},
        steps=[
            {"tool": "port_scan", "input": {"host": "{{target}}"}, "output": "ports"},
            {"tool": "http_probe", "input": {"url": "{{target}}/{{ports}}"}},
        ],
    )
    out = await run_workflow(data, runner)
    assert calls[0] == ("port_scan", {"host": "app.test"})
    # second step saw target AND the first step's output substituted
    assert calls[1][1]["url"] == "app.test/22\n80"
    assert "workflow complete" in out


async def test_for_each_iterates_items() -> None:
    runner, calls = _recorder({"port_scan": "22, 80, 443"})
    data = RunWorkflowInput(
        variables={"target": "app.test"},
        steps=[
            {"tool": "port_scan", "input": {"host": "{{target}}"}, "output": "ports"},
            {"tool": "banner_grab", "input": {"host": "{{target}}", "port": "{{item}}"},
             "for_each": "{{ports}}"},
        ],
    )
    await run_workflow(data, runner)
    banner_ports = [inp["port"] for tool, inp in calls if tool == "banner_grab"]
    assert banner_ports == ["22", "80", "443"]  # split on commas, one call each


async def test_condition_skips_step() -> None:
    runner, calls = _recorder({"port_scan": "nginx/1.14"})
    data = RunWorkflowInput(
        steps=[
            {"tool": "port_scan", "input": {}, "output": "banner"},
            {"tool": "exploit_run", "input": {"target": "x"}, "condition": "{{banner}} contains nginx"},
            {"tool": "exploit_run", "input": {"target": "y"}, "condition": "{{banner}} contains apache"},
        ],
    )
    out = await run_workflow(data, runner)
    exploits = [inp["target"] for tool, inp in calls if tool == "exploit_run"]
    assert exploits == ["x"]  # nginx matched, apache skipped
    assert "skipped (condition false)" in out


async def test_stops_at_first_failure() -> None:
    runner, calls = _recorder({"port_scan": "ok", "exploit_run": "FAIL"})
    data = RunWorkflowInput(
        steps=[
            {"tool": "port_scan", "input": {}},
            {"tool": "exploit_run", "input": {}},
            {"tool": "generate_report", "input": {}},  # must NOT run
        ],
    )
    out = await run_workflow(data, runner)
    assert "stopped at step 1" in out
    assert not any(tool == "generate_report" for tool, _ in calls)
