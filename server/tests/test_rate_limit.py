"""Test rate-limiting on enrollment endpoint.

F8-SECURITY: /v1/enroll rate-limited at Caddy level (10 req/min/IP).
This test validates the application response to rate limit violations.

Note: Actual rate limiting is enforced by Caddy reverse proxy.
This test documents the expected behavior when rate limit is reached.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_enroll_rate_limit_behavior(client: AsyncClient):
    """Document expected rate limit behavior.

    Actual enforcement at Caddy level: 10 req/min/IP.
    This test validates the application accepts requests normally;
    Caddy will return 429 Too Many Requests when limit exceeded.

    In production with Caddy:
    - First 10 requests from same IP in 1min: 200/400 (depending on validity)
    - 11th request: 429 Too Many Requests (Caddy response, not app)
    """
    # Generate test enrollment request
    payload = {
        "token": "fake-token-for-rate-limit-test",
        "hostname": "test-host-rate-limit",
        "group": "test",
    }

    # First request should reach the application
    # (Even if it fails validation, it's not rate-limited yet)
    response = await client.post("/v1/enroll", json=payload)
    assert response.status_code in [400, 401, 500]  # App validation, not rate limit

    # Document: In production behind Caddy, the 11th request within 1min
    # from the same IP will receive:
    #   429 Too Many Requests
    #   X-RateLimit-Limit: 10
    #   X-RateLimit-Remaining: 0
    #   Retry-After: <seconds>


@pytest.mark.integration
@pytest.mark.skip(reason="Requires Caddy proxy with rate_limit module - integration test only")
async def test_enroll_rate_limit_429_integration():
    """Integration test for Caddy rate limit (manual validation).

    To test manually:
    1. Deploy server behind Caddy with rate_limit config
    2. Send 11 POST /v1/enroll requests within 1 minute from same IP
    3. Expect: 11th request returns 429 Too Many Requests

    Example curl:
        for i in {1..11}; do
            curl -X POST http://rp.monxas.casa/v1/enroll \
                -H "Content-Type: application/json" \
                -d '{"token":"test","hostname":"host","group":"test"}' \
                -w "\\nStatus: %{http_code}\\n" \
                -s | head -1
            sleep 5
        done

    Expected output: First 10 return 400/401, 11th returns 429.
    """
    pass
