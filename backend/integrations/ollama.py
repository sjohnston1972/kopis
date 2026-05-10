"""Ollama API client for local inference."""

import json

import httpx
import structlog

from config import settings

log = structlog.get_logger()


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = settings.ollama_url.rstrip("/")
        self.model = settings.ollama_model

    async def generate(
        self,
        prompt: str,
        system: str = "",
        model: str | None = None,
        temperature: float = 0.1,
        format: str | None = "json",
    ) -> dict:
        """Send a generate request to Ollama and return the parsed response.

        Args:
            prompt: The user prompt.
            system: Optional system prompt.
            model: Override the default model.
            temperature: Sampling temperature.
            format: Response format — "json" for structured output, None for freeform.

        Returns:
            Parsed JSON dict if format="json", otherwise {"text": raw_response}.
        """
        payload: dict = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if format:
            payload["format"] = format

        # Aggressive 30s timeout: this is Tier 0 (fast triage). If the local
        # model doesn't respond inside that window the deterministic fallback
        # in normaliser_node takes over — far better than blocking the whole
        # snapshot pipeline waiting on a slow local model.
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{self.base_url}/api/generate", json=payload)
            r.raise_for_status()

        body = r.json()
        raw = body.get("response", "")
        tokens = body.get("eval_count", 0) + body.get("prompt_eval_count", 0)

        if format == "json":
            try:
                parsed = json.loads(raw)
                parsed["_tokens"] = tokens
                return parsed
            except json.JSONDecodeError:
                log.warning("ollama_json_parse_failed", raw=raw[:200])
                return {"_raw": raw, "_tokens": tokens, "_parse_error": True}
        else:
            return {"text": raw, "_tokens": tokens}


ollama_client = OllamaClient()
