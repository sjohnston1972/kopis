"""Regression coverage for truncated/unparseable LLM response refusal.

Kopis stores Anthropic-generated remediation commands and, once approved,
pushes them to live network devices. A response cut off by the model's
token limit can close into syntactically valid but semantically INCOMPLETE
JSON — e.g. a `commands` array missing its last, most important entry —
which is how a partial config push ends up on a router (see issues
#18/#19, referenced throughout `integrations/anthropic.py` and
`agents/nodes/_llm_guard.py`).

This file covers the guard at its two layers:
  1. `AnthropicClient.message()` — the truncation/parse-error DETECTION.
  2. `llm_result_unusable()` — the shared REFUSAL check every agent node
     runs before trusting a result.

Coverage for the same guard exercised at each of the four call sites
(the agent nodes) lives in test_agent_nodes_truncation.py.

No network access: outbound HTTP is stubbed by monkeypatching
`httpx.AsyncClient` in `integrations.anthropic`. No database is touched by
anything in this file, so it runs standalone (no Postgres needed).
"""

import ast
import json
from pathlib import Path

import pytest

from integrations.anthropic import AnthropicClient
import integrations.anthropic as anthropic_module
from agents.nodes._llm_guard import llm_result_unusable


# ── Fake httpx.AsyncClient plumbing ─────────────────────────────────────


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient — records the request, returns a
    canned response body regardless of what was posted.
    """

    last_instance: "_FakeAsyncClient | None" = None

    def __init__(self, *args, **kwargs):
        self.posted = None
        _FakeAsyncClient.last_instance = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self.posted = {"url": url, "headers": headers, "json": json}
        return _FakeResponse(_FakeAsyncClient.response_body)


def _install_fake_http(monkeypatch, response_body: dict):
    _FakeAsyncClient.response_body = response_body
    monkeypatch.setattr(anthropic_module.httpx, "AsyncClient", _FakeAsyncClient)


def _anthropic_body(*, stop_reason: str, text: str, input_tokens=100, output_tokens=50) -> dict:
    return {
        "stop_reason": stop_reason,
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


# ── AnthropicClient.message() ────────────────────────────────────────────


class TestAnthropicClientMessage:
    @pytest.mark.asyncio
    async def test_max_tokens_stop_reason_yields_truncation_marker(self, monkeypatch):
        # Even though the text looks like it COULD be completed, stop_reason
        # is the only signal trusted — the content is never inspected/repaired.
        body = _anthropic_body(
            stop_reason="max_tokens",
            text='{"recommendations": [{"commands": ["interface Gi0/1", "no shu',
        )
        _install_fake_http(monkeypatch, body)
        client = AnthropicClient()

        result = await client.message(prompt="do the thing", model="claude-x")

        assert result == {"_truncated": True, "_tokens": 150, "_model": "claude-x"}
        assert "_parse_error" not in result

    @pytest.mark.asyncio
    async def test_malformed_json_yields_parse_error_marker(self, monkeypatch):
        body = _anthropic_body(stop_reason="end_turn", text="this is not json at all {{{")
        _install_fake_http(monkeypatch, body)
        client = AnthropicClient()

        result = await client.message(prompt="do the thing", model="claude-x")

        assert result["_parse_error"] is True
        assert result["_tokens"] == 150
        assert result["_model"] == "claude-x"
        assert result["text"] == "this is not json at all {{{"
        assert "_truncated" not in result

    @pytest.mark.asyncio
    async def test_complete_response_parses_normally(self, monkeypatch):
        payload = {"recommendations": [{"action_description": "re-enable interface", "commands": ["no shutdown"]}]}
        body = _anthropic_body(stop_reason="end_turn", text=json.dumps(payload))
        _install_fake_http(monkeypatch, body)
        client = AnthropicClient()

        result = await client.message(prompt="do the thing", model="claude-x")

        assert result["recommendations"] == payload["recommendations"]
        assert result["_tokens"] == 150
        assert result["_model"] == "claude-x"
        assert "_truncated" not in result
        assert "_parse_error" not in result

    @pytest.mark.asyncio
    async def test_complete_response_in_markdown_fence_parses_normally(self, monkeypatch):
        payload = {"findings": []}
        text = f"```json\n{json.dumps(payload)}\n```"
        body = _anthropic_body(stop_reason="end_turn", text=text)
        _install_fake_http(monkeypatch, body)
        client = AnthropicClient()

        result = await client.message(prompt="do the thing", model="claude-x")

        assert result["findings"] == []
        assert "_parse_error" not in result

    @pytest.mark.asyncio
    async def test_truncated_looking_json_with_end_turn_is_never_repaired(self, monkeypatch):
        """The core regression this file exists for: a response that LOOKS
        like it's just missing closing braces/brackets — exactly the shape
        the old brace-patching code used to "fix" — must be refused as a
        parse error, not silently completed into a usable dict. stop_reason
        here is deliberately NOT max_tokens (that path is covered above);
        this proves there's no separate brace-counting rescue for
        already-malformed JSON either.
        """
        text = '{"recommendations": [{"action_description": "fix it", "commands": ["no shutdown"'
        body = _anthropic_body(stop_reason="end_turn", text=text)
        _install_fake_http(monkeypatch, body)
        client = AnthropicClient()

        result = await client.message(prompt="do the thing", model="claude-x")

        assert result["_parse_error"] is True
        assert "recommendations" not in result

    def test_brace_patching_repair_path_is_genuinely_gone(self):
        """Static check that no brace-counting/JSON-repair helper exists
        anywhere in the module — this is what issue #18/#19's fix actually
        removed, per the module docstring ("stop brace-patching JSON").
        Walk the AST rather than grep so this can't be fooled by comments.
        """
        source = Path(anthropic_module.__file__).read_text()
        tree = ast.parse(source)
        suspicious_terms = ("repair", "brace", "patch")

        function_names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert not any(
            term in name.lower() for name in function_names for term in suspicious_terms
        ), f"found a suspicious repair-shaped function: {function_names}"

        # No source line outside of comments/docstrings does brace counting
        # or blind brace-appending to coerce invalid JSON into parsing.
        assert 'text.count("{")' not in source
        assert 'text.count("}")' not in source
        assert "+= '}'" not in source
        assert '+= "}"' not in source


# ── llm_result_unusable() ────────────────────────────────────────────────


class TestLlmResultUnusable:
    def test_truncated_result_is_unusable(self):
        reason = llm_result_unusable(
            {"_truncated": True, "_tokens": 10, "_model": "claude-x"},
            node="remediation",
            hostname="r1",
        )
        assert reason is not None
        assert "max_tokens" in reason

    def test_parse_error_result_is_unusable(self):
        reason = llm_result_unusable(
            {"_parse_error": True, "text": "garbage", "_tokens": 10, "_model": "claude-x"},
            node="topology",
            hostname="r1",
        )
        assert reason is not None
        assert "not valid JSON" in reason

    def test_normal_result_is_usable(self):
        reason = llm_result_unusable(
            {"findings": [], "_tokens": 10, "_model": "claude-x"},
            node="topology",
            hostname="r1",
        )
        assert reason is None
