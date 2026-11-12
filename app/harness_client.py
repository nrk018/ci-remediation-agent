"""Check a Harness personal access token. The token is never returned or logged."""

from __future__ import annotations

import httpx

from app.config import Settings


def probe_harness(settings: Settings, transport: httpx.BaseTransport | None = None) -> str:
    """Return ok, down, or unconfigured. The result never contains the token."""
    if not settings.harness_api_token:
        return "unconfigured"
    url = settings.harness_base_url.rstrip("/") + "/gateway/ng/api/user/currentUser"
    headers = {"x-api-key": settings.harness_api_token}
    if settings.harness_account_id:
        headers["Harness-Account"] = settings.harness_account_id
    try:
        with httpx.Client(transport=transport, timeout=10.0) as client:
            response = client.get(url, headers=headers)
    except httpx.HTTPError:
        return "down"
    if response.status_code == 200:
        return "ok"
    return "down"
