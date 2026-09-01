"""Shared guard against truncated/parse-errored LLM responses.

Every node in this package calls `anthropic_client.message()` and gets back
either a well-formed dict or one flagged `_truncated` (stop_reason ==
"max_tokens") / `_parse_error` (invalid JSON). Neither of those may be
treated as a normal result: doing so risks turning a partial commands list
into a stored recommendation, an approval, and ultimately a partial config
push to a live device (see issues #18/#19).
"""

import structlog

log = structlog.get_logger()


def llm_result_unusable(result: dict, *, node: str, hostname: str) -> str | None:
    """Return a human-readable reason if `result` must be discarded.

    Returns None if the result is safe to use.
    """
    if result.get("_truncated"):
        reason = "response truncated by the model's token limit (stop_reason=max_tokens)"
    elif result.get("_parse_error"):
        reason = "response was not valid JSON"
    else:
        return None

    log.warning(
        f"{node}_unusable_llm_response",
        hostname=hostname,
        reason=reason,
        tokens=result.get("_tokens", 0),
        model=result.get("_model"),
    )
    return reason
