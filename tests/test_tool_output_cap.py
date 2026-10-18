from hexharness.agent.loop import MAX_TOOL_OUTPUT_CHARS, _cap_tool_output


def test_small_output_unchanged():
    out = "x" * 100
    assert _cap_tool_output(out) == out


def test_at_limit_unchanged():
    out = "y" * MAX_TOOL_OUTPUT_CHARS
    assert _cap_tool_output(out) == out


def test_huge_output_capped_keeps_head_and_tail():
    out = "A" * 30 + "B" * (MAX_TOOL_OUTPUT_CHARS * 10) + "C" * 30
    r = _cap_tool_output(out)
    assert r.startswith("A")          # head preserved
    assert r.endswith("C")            # tail preserved
    assert "elided by HexHarness" in r
    # bounded well under the provider per-string limit (OpenAI Responses: 10 MB)
    assert len(r) <= MAX_TOOL_OUTPUT_CHARS + 300
