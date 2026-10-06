"""Pure mapping helpers for the OpenAI/Google/Ollama adapters.

Imports the modules WITHOUT instantiating a real client, so no SDK/network needed.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from hexharness.providers import google as g
from hexharness.providers import openai as o
from hexharness.providers.types import (
    Message,
    Role,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)


def _conversation():
    return [
        Message.user_text("scan acme.example"),
        Message(role=Role.ASSISTANT, content=[
            TextBlock(text="checking"),
            ToolUseBlock(id="t1", name="dns_lookup", input={"host": "acme.example"}),
        ]),
        Message(role=Role.USER, content=[
            ToolResultBlock(tool_use_id="t1", content="resolved", is_error=False),
        ]),
    ]


# --- OpenAI ---------------------------------------------------------------

def test_openai_messages_shape_and_system():
    api = o.to_openai_messages(_conversation(), system="be careful")
    assert api[0] == {"role": "system", "content": "be careful"}
    assert api[1] == {"role": "user", "content": "scan acme.example"}
    asst = api[2]
    assert asst["role"] == "assistant" and asst["content"] == "checking"
    call = asst["tool_calls"][0]
    assert call == {
        "id": "t1",
        "type": "function",
        "function": {"name": "dns_lookup", "arguments": json.dumps({"host": "acme.example"})},
    }
    assert api[3] == {"role": "tool", "tool_call_id": "t1", "content": "resolved"}


def test_openai_tools_mapping():
    spec = ToolSpec(name="x", description="d", input_schema={"type": "object"})
    assert o.tools_to_openai([spec]) == [
        {"type": "function", "function": {"name": "x", "description": "d", "parameters": {"type": "object"}}}
    ]


def test_openai_from_response_parses_tool_calls_and_usage():
    resp = SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason="tool_calls",
            message=SimpleNamespace(
                content="thinking",
                tool_calls=[SimpleNamespace(
                    id="c1",
                    function=SimpleNamespace(name="cwe_lookup", arguments='{"cwe_id": "79"}'),
                )],
            ),
        )],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=5),
        model="gpt-4o",
    )
    out = o.from_openai_response(resp)
    assert out.stop_reason is StopReason.TOOL_USE
    assert out.usage.total_tokens == 16
    assert out.text() == "thinking"
    tu = out.tool_uses()[0]
    assert tu.name == "cwe_lookup" and tu.input == {"cwe_id": "79"}


def test_openai_from_response_plain_text():
    resp = SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content="done", tool_calls=None),
        )],
        usage=None,
        model="gpt-4o",
    )
    out = o.from_openai_response(resp)
    assert out.stop_reason is StopReason.END_TURN and out.text() == "done"


# --- Google ---------------------------------------------------------------

def test_genai_contents_roles_and_function_parts():
    contents = g.to_genai_contents(_conversation())
    assert contents[0] == {"role": "user", "parts": [{"text": "scan acme.example"}]}
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][1] == {
        "function_call": {"name": "dns_lookup", "args": {"host": "acme.example"}}
    }
    # tool_use_id resolves back to the declared function name
    assert contents[2]["parts"][0] == {
        "function_response": {"name": "dns_lookup", "response": {"output": "resolved"}}
    }


def test_genai_tools_mapping():
    spec = ToolSpec(name="x", description="d", input_schema={"type": "object"})
    assert g.tools_to_genai([spec]) == [
        {"function_declarations": [{"name": "x", "description": "d", "parameters": {"type": "object"}}]}
    ]


def test_genai_from_response_dict_parts():
    resp = SimpleNamespace(
        candidates=[SimpleNamespace(
            finish_reason="STOP",
            content={"parts": [
                {"text": "hi"},
                {"function_call": {"name": "dns_lookup", "args": {"host": "a"}}},
            ]},
        )],
        usage_metadata=SimpleNamespace(prompt_token_count=7, candidates_token_count=3),
        model_version="gemini-2.0-flash",
    )
    out = g.from_genai_response(resp)
    assert out.stop_reason is StopReason.END_TURN
    assert out.usage.total_tokens == 10
    assert out.text() == "hi"
    assert out.tool_uses()[0].input == {"host": "a"}


# --- Ollama reuses the OpenAI helpers -------------------------------------

def test_ollama_imports_and_reuses_openai_mapping():
    from hexharness.providers import ollama

    assert ollama.OllamaProvider.name == "ollama"
    assert ollama.to_openai_messages is o.to_openai_messages
