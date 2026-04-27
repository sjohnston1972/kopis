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
        {"text": raw_text, "_tokens": count}.
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
        raw_text = ""
        for block in body.get("content", []):
            if block.get("type") == "text":
                raw_text += block["text"]

        usage = body.get("usage", {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

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
                # Fences opened but never closed (truncated response) — strip the opening fence
                lines = text.split("\n")
                if lines and lines[0].strip().startswith("```"):
                    lines = lines[1:]
                text = "\n".join(lines)

        # Handle truncated JSON — try to close open braces/brackets
        for attempt in range(3):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    parsed["_tokens"] = tokens
                    parsed["_model"] = model
                return parsed
            except json.JSONDecodeError as e:
                # If truncated, try adding closing braces
                if "Expecting" in str(e) or "Unterminated" in str(e):
                    # Count unclosed structures
                    open_braces = text.count("{") - text.count("}")
                    open_brackets = text.count("[") - text.count("]")
                    if open_braces > 0 or open_brackets > 0:
                        # Strip trailing comma or partial value
                        text = text.rstrip().rstrip(",")
                        text += "]" * open_brackets + "}" * open_braces
                        continue
                break

        return {"text": raw_text, "_tokens": tokens, "_model": model, "_parse_error": True}


anthropic_client = AnthropicClient()
