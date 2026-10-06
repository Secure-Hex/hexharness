"""Normalized <-> Anthropic API mapping is lossless for the blocks we use."""
from __future__ import annotations

from types import SimpleNamespace

from hexharness.providers.anthropic import from_api_response, to_api_messages
from hexharness.providers.types import (
    Message,
    Role,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def test_to_api_messages_roundtrips_block_shapes():
    msgs = [
        Message.user_text("hi"),
        Message(role=Role.ASSISTANT, content=[
            TextBlock(text="let me check"),
            ToolUseBlock(id="t1", name="dns_lookup", input={"host": "acme.example"}),
        ]),
        Message(role=Role.USER, content=[
            ToolResultBlock(tool_use_id="t1", content="resolved", is_error=False),
        ]),
    ]
    api = to_api_messages(msgs)
    assert api[0] == {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    assert api[1]["content"][1] == {
        "type": "tool_use", "id": "t1", "name": "dns_lookup", "input": {"host": "acme.example"}
    }
    assert api[2]["content"][0]["type"] == "tool_result"


def test_from_api_response_maps_tool_use_and_usage():
    fake = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="calling tool"),
            SimpleNamespace(type="tool_use", id="t9", name="cwe_lookup", input={"cwe_id": "79"}),
        ],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=10, output_tokens=4),
        model="claude-sonnet-4-5",
    )
    resp = from_api_response(fake)
    assert resp.stop_reason is StopReason.TOOL_USE
    assert resp.usage.total_tokens == 14
    tus = resp.tool_uses()
    assert len(tus) == 1 and tus[0].name == "cwe_lookup" and tus[0].input == {"cwe_id": "79"}
    assert resp.text() == "calling tool"
