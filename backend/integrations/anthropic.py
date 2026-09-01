"""Anthropic API client wrapper for Claude models."""

import json

import httpx
import structlog

from config import settings

log = structlog.get_logger()

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


class AnthropicClient:
    def __init__(self) -> None:
        self.api_key = settings.anthropic_api_key
        self.headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    async def message(
        self,
        prompt: str,
        system: str = "",
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> dict:
        """Send a message to the Anthropic API.

        Returns parsed JSON if the response is valid JSON, otherwise
        {"text": raw_text, "_tokens": count, "_parse_error": True}.

        A response that was cut off by the token limit
        (`stop_reason == "max_tokens"`) is NEVER parsed or "repaired" into a
        JSON dict — a truncated commands/rollback_commands array can close
        into syntactically valid but semantically incomplete JSON, which is
        how a partial config push ends up on live devices. Instead this
        returns {"_truncated": True, ...} so callers must explicitly refuse
        it rather than silently treating a guess as a real result.
        """
        model = model or settings.haiku_model
        payload: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                ANTHROPIC_API_URL, headers=self.headers, json=payload
            )
            r.raise_for_status()

        body = r.json()
        stop_reason = body.get("stop_reason")
        raw_text = ""
        for block in body.get("content", []):
            if block.get("type") == "text":
                raw_text += block["text"]

        usage = body.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        tokens = input_tokens + output_tokens

        # stop_reason is the API's own, reliable truncation signal — trust
        # it instead of guessing from brace-counting. Never brace-patch a
        # max_tokens response into a "successful" parse.
        if stop_reason == "max_tokens":
            log.warning(
                "anthropic_response_truncated",
                model=model,
                stop_reason=stop_reason,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            return {"_truncated": True, "_tokens": tokens, "_model": model}

        # Try to parse as JSON (strip markdown fences if present)
        text = raw_text.strip()

        # Extract JSON from markdown code fences: ```json ... ```
        if "```" in text:
            import re
            # Match the first JSON block inside fences
            m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
            if m:
                text = m.group(1).strip()
            else:
                # Fences opened but never closed — strip the opening fence
                lines = text.split("\n")
                if lines and lines[0].strip().startswith("```"):
                    lines = lines[1:]
                text = "\n".join(lines)

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                parsed["_tokens"] = tokens
                parsed["_model"] = model
            return parsed
        except json.JSONDecodeError as e:
            log.warning(
                "anthropic_response_parse_error",
                model=model,
                stop_reason=stop_reason,
                error=str(e),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        return {"text": raw_text, "_tokens": tokens, "_model": model, "_parse_error": True}


anthropic_client = AnthropicClient()
