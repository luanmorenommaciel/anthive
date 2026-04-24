"""anthive Langfuse client — read-only query client for cost/token metrics.

Public API:
    LangfuseClient(base_url, public_key, secret_key, *, timeout) -> client
    client.get_session_metrics(session_id) -> dict
    client.is_configured() -> bool
    client.health() -> bool

Design rules:
- get_session_metrics never raises; returns zero-values on any failure.
- is_configured() returns True only when both keys are non-empty strings.
- health() returns True when the Langfuse /api/public/health endpoint is reachable.
"""

from __future__ import annotations

import logging

import httpx

__all__ = ["LangfuseClient", "ZERO_METRICS"]

logger = logging.getLogger(__name__)

# Sentinel returned on any failure so the dashboard always has something to show.
ZERO_METRICS: dict = {
    "tokens_in": 0,
    "tokens_out": 0,
    "cost_usd": 0.0,
    "duration_s": 0.0,
    "trace_id": None,
    "url": None,
}


class LangfuseClient:
    """Read-only HTTP client for the Langfuse sessions API."""

    def __init__(
        self,
        base_url: str,
        public_key: str | None = None,
        secret_key: str | None = None,
        *,
        timeout: float = 5.0,
    ) -> None:
        """Initialize the client with credentials and base URL."""
        self._base = base_url.rstrip("/")
        self._public_key = public_key or ""
        self._secret_key = secret_key or ""
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return True if both API keys are non-empty strings."""
        return bool(self._public_key and self._secret_key)

    def health(self) -> bool:
        """Return True if the Langfuse health endpoint responds with 2xx."""
        try:
            resp = httpx.get(
                f"{self._base}/api/public/health",
                timeout=self._timeout,
            )
            return resp.is_success
        except (httpx.HTTPError, httpx.RequestError) as exc:
            logger.warning("Langfuse health check failed: %s", exc)
            return False

    def get_session_metrics(self, session_id: str) -> dict:
        """Return cost/token metrics for *session_id* from Langfuse.

        Returns zero-valued ZERO_METRICS on any network or auth failure.
        """
        if not self.is_configured():
            logger.debug(
                "get_session_metrics: client not configured (no API keys); "
                "returning zero metrics for session %s.",
                session_id,
            )
            return dict(ZERO_METRICS)

        try:
            resp = httpx.get(
                f"{self._base}/api/public/sessions",
                params={"filter[metadata][session_id]": session_id},
                auth=(self._public_key, self._secret_key),
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.RequestError) as exc:
            logger.warning(
                "get_session_metrics: request failed for session %s: %s",
                session_id,
                exc,
            )
            return dict(ZERO_METRICS)

        try:
            payload = resp.json()
            data: list = payload.get("data", [])
            if not data:
                return dict(ZERO_METRICS)

            entry: dict = data[0]
            usage: dict = entry.get("usage", {})
            trace_id: str | None = entry.get("id")
            url: str | None = f"{self._base}/sessions/{trace_id}" if trace_id else None

            return {
                "tokens_in": int(usage.get("promptTokens", 0) or 0),
                "tokens_out": int(usage.get("completionTokens", 0) or 0),
                "cost_usd": float(entry.get("totalCost", 0.0) or 0.0),
                "duration_s": float(entry.get("latency", 0) or 0) / 1000.0,
                "trace_id": trace_id,
                "url": url,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "get_session_metrics: failed to parse Langfuse response for %s: %s",
                session_id,
                exc,
            )
            return dict(ZERO_METRICS)
