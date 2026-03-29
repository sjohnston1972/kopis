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
        if text.startswith("```"):
            # Remove ```json ... ``` wrapper
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                parsed["_tokens"] = tokens
                parsed["_model"] = model
            return parsed
        except (json.JSONDecodeError, ValueError):
            return {"text": raw_text, "_tokens": tokens, "_model": model}


anthropic_client = AnthropicClient()
