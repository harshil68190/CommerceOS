"""
tests/test_auth.py

Responsibility
--------------
End-to-end tests for the authentication module, exercising the real
HTTP layer (via `TestClient`) against a real Postgres database and real
Redis instance — not mocks. This is deliberate: the value being tested
(password hashing actually round-trips, unique constraints actually
reject duplicates, refresh-token rotation actually invalidates the old
token in Redis) only means something when tested against the real
things, not fakes standing in for them.
"""

from fastapi.testclient import TestClient

VALID_PASSWORD = "Str0ng!Pass1"


def _register_payload(**overrides) -> dict:
    """Builds a valid registration payload, with any fields overridden
    per-test to exercise a specific validation rule."""
    payload = {
        "email": "jane@example.com",
        "username": "jane_doe",
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD,
        "first_name": "Jane",
        "last_name": "Doe",
        "phone": "+1234567890",
    }
    payload.update(overrides)
    return payload


class TestRegister:
    def test_register_returns_created_user(self, client: TestClient) -> None:
        response = client.post("/api/v1/auth/register", json=_register_payload())

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "jane@example.com"
        assert body["username"] == "jane_doe"
        assert body["role"] == "customer"
        assert body["is_active"] is True
        assert body["is_verified"] is False
        assert "hashed_password" not in body
        assert "password" not in body

    def test_register_rejects_duplicate_email(self, client: TestClient) -> None:
        client.post("/api/v1/auth/register", json=_register_payload())

        response = client.post(
            "/api/v1/auth/register",
            json=_register_payload(username="a_different_username"),
        )

        assert response.status_code == 409
        assert response.json()["error_code"] == "CONFLICT"

    def test_register_rejects_duplicate_username(self, client: TestClient) -> None:
        client.post("/api/v1/auth/register", json=_register_payload())

        response = client.post(
            "/api/v1/auth/register",
            json=_register_payload(email="different@example.com"),
        )

        assert response.status_code == 409

    def test_register_rejects_weak_password(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/register",
            json=_register_payload(password="weak", confirm_password="weak"),
        )

        assert response.status_code == 422

    def test_register_rejects_mismatched_passwords(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/register",
            json=_register_payload(confirm_password="SomethingDifferent1!"),
        )

        assert response.status_code == 422


class TestLogin:
    def test_login_returns_token_pair(self, client: TestClient) -> None:
        client.post("/api/v1/auth/register", json=_register_payload())

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "jane@example.com", "password": VALID_PASSWORD},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["refresh_token"]

    def test_login_rejects_wrong_password(self, client: TestClient) -> None:
        client.post("/api/v1/auth/register", json=_register_payload())

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "jane@example.com", "password": "WrongPassword1!"},
        )

        assert response.status_code == 401

    def test_login_rejects_unknown_email_with_same_error_as_wrong_password(
        self, client: TestClient
    ) -> None:
        # Same status code AND message as a wrong-password attempt is
        # deliberate — see AuthService.authenticate's docstring on
        # avoiding user enumeration.
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": VALID_PASSWORD},
        )

        assert response.status_code == 401
        assert response.json()["message"] == "Invalid email or password."


class TestMe:
    def test_me_returns_current_user_with_valid_token(self, client: TestClient) -> None:
        client.post("/api/v1/auth/register", json=_register_payload())
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "jane@example.com", "password": VALID_PASSWORD},
        )
        access_token = login_response.json()["access_token"]

        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
        )

        assert response.status_code == 200
        assert response.json()["email"] == "jane@example.com"

    def test_me_rejects_missing_token(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401

    def test_me_rejects_garbage_token(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 401


class TestRefreshAndLogout:
    def _login(self, client: TestClient) -> dict:
        client.post("/api/v1/auth/register", json=_register_payload())
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "jane@example.com", "password": VALID_PASSWORD},
        )
        return response.json()

    def test_refresh_returns_new_token_pair(self, client: TestClient) -> None:
        tokens = self._login(client)

        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )

        assert response.status_code == 200
        new_tokens = response.json()
        assert new_tokens["access_token"] != tokens["access_token"]
        assert new_tokens["refresh_token"] != tokens["refresh_token"]

    def test_refresh_rotation_invalidates_old_refresh_token(
        self, client: TestClient
    ) -> None:
        tokens = self._login(client)

        # First use succeeds and rotates the token...
        first = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert first.status_code == 200

        # ...so reusing the original refresh token must now fail.
        second = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert second.status_code == 401

    def test_logout_revokes_refresh_token(self, client: TestClient) -> None:
        tokens = self._login(client)

        logout_response = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert logout_response.status_code == 204

        refresh_response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refresh_response.status_code == 401

    def test_logout_requires_authentication(self, client: TestClient) -> None:
        tokens = self._login(client)

        response = client.post(
            "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
        )

        assert response.status_code == 401
