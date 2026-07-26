"""
tests/test_health.py

Responsibility
--------------
Verifies the `/api/v1/health` liveness endpoint behaves exactly as
specified: HTTP 200 with body `{"status": "healthy"}`. This is also the
first smoke test that the app factory, middleware stack, and router
aggregation all wire together correctly end-to-end.
"""

from fastapi.testclient import TestClient


def test_health_check_returns_healthy_status(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_health_check_response_includes_request_id_header(client: TestClient) -> None:
    # Confirms the request-ID middleware ran and stamped the response,
    # since every future test/log-correlation workflow depends on this.
    response = client.get("/api/v1/health")

    assert "X-Request-ID" in response.headers
