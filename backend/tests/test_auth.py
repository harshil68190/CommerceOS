from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models.user import User, UserRole

VALID_PASSWORD = "Str0ng!Pass1"


def _register_payload(**overrides) -> dict:
    unique = uuid4().hex[:10]
    payload = {
        "email": f"user_{unique}@example.com",
        "username": f"user_{unique}",
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD,
        "first_name": "Test",
        "last_name": "User",
        "phone": "+1234567890",
    }
    payload.update(overrides)
    return payload


def _login_form(email: str, password: str) -> dict:
    return {"username": email, "password": password}


def _assert_error_envelope(response, *, status_code: int, error_code: str, message: str | None = None) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
    assert body["error_code"] == error_code
    if message is not None:
        assert body["message"] == message


def _jwt_token(*, sub: str, role: str, token_type: str, expires_delta: timedelta, secret: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid4()),
    }
    settings = get_settings()
    return jwt.encode(payload, secret, algorithm=settings.JWT_ALGORITHM)


class TestRegistration:
    def test_user_registration(self, client: TestClient) -> None:
        payload = _register_payload()
        response = client.post("/api/v1/auth/register", json=payload)

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == payload["email"]
        assert body["username"] == payload["username"]
        assert body["role"] == "customer"
        assert "hashed_password" not in body

    def test_duplicate_email_registration(self, client: TestClient) -> None:
        payload = _register_payload()
        client.post("/api/v1/auth/register", json=payload)

        response = client.post(
            "/api/v1/auth/register",
            json=_register_payload(email=payload["email"]),
        )

        _assert_error_envelope(
            response,
            status_code=409,
            error_code="CONFLICT",
            message="An account with this email already exists.",
        )

    def test_duplicate_username_registration(self, client: TestClient) -> None:
        payload = _register_payload()
        client.post("/api/v1/auth/register", json=payload)

        response = client.post(
            "/api/v1/auth/register",
            json=_register_payload(username=payload["username"]),
        )

        _assert_error_envelope(
            response,
            status_code=409,
            error_code="CONFLICT",
            message="This username is already taken.",
        )

    @pytest.mark.parametrize(
        ("password_value", "expected_fragment"),
        [
            ("Ab1!", "at least 8 characters"),
            ("NOLOWERCASE1!", "lowercase letter"),
            ("nouppercase1!", "uppercase letter"),
            ("NoDigits!@#", "digit"),
            ("NoSpecialChar1", "special character"),
        ],
    )
    def test_weak_password_rejected(
        self, client: TestClient, password_value: str, expected_fragment: str
    ) -> None:
        payload = _register_payload(password=password_value, confirm_password=password_value)
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == "REQUEST_VALIDATION_ERROR"
        detail_str = str(body.get("details", {}))
        assert expected_fragment.lower() in detail_str.lower()

    def test_password_mismatch_rejected(self, client: TestClient) -> None:
        payload = _register_payload(confirm_password="DifferentPass1!")
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == "REQUEST_VALIDATION_ERROR"
        error_str = str(body.get("details", {}))
        assert "do not match" in error_str.lower()


class TestLogin:
    def test_successful_login(self, client: TestClient) -> None:
        payload = _register_payload()
        client.post("/api/v1/auth/register", json=payload)

        response = client.post(
            "/api/v1/auth/login",
            data=_login_form(payload["email"], VALID_PASSWORD),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["refresh_token"]

    def test_invalid_password(self, client: TestClient) -> None:
        payload = _register_payload()
        client.post("/api/v1/auth/register", json=payload)

        response = client.post(
            "/api/v1/auth/login",
            data=_login_form(payload["email"], "WrongPassword1!"),
        )

        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid email or password.",
        )

    def test_non_existent_user(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/login",
            data=_login_form("nobody@example.com", VALID_PASSWORD),
        )

        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid email or password.",
        )

    def test_disabled_user(self, client: TestClient, user_factory) -> None:
        user = user_factory(role=UserRole.CUSTOMER, is_active=False)
        response = client.post(
            "/api/v1/auth/login",
            data=_login_form(user.email, VALID_PASSWORD),
        )

        _assert_error_envelope(
            response,
            status_code=403,
            error_code="FORBIDDEN",
            message="This account has been deactivated.",
        )


class TestRefreshAndLogout:
    def _login(self, client: TestClient) -> tuple[dict, dict]:
        payload = _register_payload()
        client.post("/api/v1/auth/register", json=payload)
        response = client.post(
            "/api/v1/auth/login",
            data=_login_form(payload["email"], VALID_PASSWORD),
        )
        return payload, response.json()

    def test_refresh_token(self, client: TestClient) -> None:
        _, tokens = self._login(client)

        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )

        assert response.status_code == 200
        new_tokens = response.json()
        assert new_tokens["access_token"] != tokens["access_token"]
        assert new_tokens["refresh_token"] != tokens["refresh_token"]

    @pytest.mark.parametrize("token", ["not-a-token", "Bearer abc"])
    def test_invalid_refresh_token(self, client: TestClient, token: str) -> None:
        response = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid or expired token.",
        )

    def test_expired_refresh_token(self, client: TestClient, customer_user: User) -> None:
        settings = get_settings()
        expired_refresh = _jwt_token(
            sub=str(customer_user.id),
            role=customer_user.role.value,
            token_type="refresh",
            expires_delta=timedelta(minutes=-1),
            secret=settings.JWT_SECRET_KEY,
        )

        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": expired_refresh}
        )
        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid or expired token.",
        )

    def test_logout(self, client: TestClient) -> None:
        _, tokens = self._login(client)
        response = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert response.status_code == 204

        refresh_again = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        _assert_error_envelope(
            refresh_again,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid or expired token.",
        )

    def test_logout_with_invalid_token(
        self, authenticated_customer_client: TestClient
    ) -> None:
        response = authenticated_customer_client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "bad-refresh-token"},
        )
        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid or expired token.",
        )


class TestProtectedEndpointAndTokenValidation:
    def test_access_protected_endpoint_with_valid_token(
        self, authenticated_customer_client: TestClient
    ) -> None:
        response = authenticated_customer_client.get("/api/v1/auth/me")
        assert response.status_code == 200

    def test_access_protected_endpoint_without_token(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/me")
        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Not authenticated",
        )

    @pytest.mark.parametrize(
        ("header", "expected_message"),
        [
            ("Bearer", "Invalid or expired token."),
            ("Bearer invalid.jwt.token", "Invalid or expired token."),
            ("garbage", "Not authenticated"),
        ],
    )
    def test_access_protected_endpoint_with_malformed_token(
        self, client: TestClient, header: str, expected_message: str
    ) -> None:
        response = client.get("/api/v1/auth/me", headers={"Authorization": header})
        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message=expected_message,
        )

    def test_access_protected_endpoint_with_expired_token(
        self, client: TestClient, customer_user: User
    ) -> None:
        settings = get_settings()
        expired_access = _jwt_token(
            sub=str(customer_user.id),
            role=customer_user.role.value,
            token_type="access",
            expires_delta=timedelta(minutes=-1),
            secret=settings.JWT_SECRET_KEY,
        )
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_access}"}
        )
        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid or expired token.",
        )

    def test_jwt_signature_validation(self, client: TestClient, customer_user: User) -> None:
        bad_signature_token = _jwt_token(
            sub=str(customer_user.id),
            role=customer_user.role.value,
            token_type="access",
            expires_delta=timedelta(minutes=5),
            secret="different-secret",
        )
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {bad_signature_token}"}
        )
        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid or expired token.",
        )

    def test_tampered_token_rejection(self, client: TestClient, customer_token: str) -> None:
        replacement = "a" if customer_token[-1] != "a" else "b"
        tampered = customer_token[:-1] + replacement
        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"})
        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid or expired token.",
        )

    def test_issuer_audience_validation_not_implemented(self) -> None:
        settings = get_settings()
        if hasattr(settings, "JWT_ISSUER") or hasattr(settings, "JWT_AUDIENCE"):
            pytest.fail("Issuer/Audience settings exist; add enforcement tests.")

    def test_access_protected_endpoint_with_deactivated_user(
        self, client_factory, customer_user: User, access_token_factory
    ) -> None:
        """Deactivated user accessing a protected endpoint: the access
        token was issued while the user was active, but the account was
        subsequently deactivated — the endpoint should reject with 403."""
        token = access_token_factory(customer_user)
        customer_user.is_active = False
        test_client = client_factory(access_token=token)
        response = test_client.get("/api/v1/auth/me")
        _assert_error_envelope(
            response,
            status_code=403,
            error_code="FORBIDDEN",
            message="This account has been deactivated.",
        )

    def test_access_protected_endpoint_with_non_uuid_sub(
        self, client: TestClient
    ) -> None:
        """Token with valid signature but non-UUID sub (e.g. integer).
        This exercises the KeyError/ValueError catch in
        get_current_user."""
        settings = get_settings()
        bogus_sub_token = _jwt_token(
            sub="not-a-uuid",
            role="customer",
            token_type="access",
            expires_delta=timedelta(minutes=5),
            secret=settings.JWT_SECRET_KEY,
        )
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {bogus_sub_token}"}
        )
        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid or expired token.",
        )

    def test_access_protected_endpoint_with_refresh_token_type(
        self, client: TestClient, customer_user: User
    ) -> None:
        """A refresh token presented where an access token is expected
        should be rejected (wrong type claim)."""
        settings = get_settings()
        refresh_token = _jwt_token(
            sub=str(customer_user.id),
            role=customer_user.role.value,
            token_type="refresh",
            expires_delta=timedelta(minutes=5),
            secret=settings.JWT_SECRET_KEY,
        )
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh_token}"}
        )
        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid or expired token.",
        )


class TestAuthRbac:
    def test_customer_cannot_access_admin_endpoint(
        self, authenticated_customer_client: TestClient
    ) -> None:
        response = authenticated_customer_client.get("/api/v1/products/admin")
        _assert_error_envelope(
            response,
            status_code=403,
            error_code="FORBIDDEN",
        )

    def test_admin_can_access_admin_endpoint(
        self, authenticated_admin_client: TestClient
    ) -> None:
        response = authenticated_admin_client.get("/api/v1/products/admin")
        assert response.status_code == 200

    def test_unauthorized_request_returns_401(self, client: TestClient) -> None:
        response = client.get("/api/v1/products/admin")
        _assert_error_envelope(
            response,
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Not authenticated",
        )

    def test_authenticated_but_forbidden_returns_403(
        self, authenticated_customer_client: TestClient
    ) -> None:
        response = authenticated_customer_client.get("/api/v1/products/admin")
        _assert_error_envelope(
            response,
            status_code=403,
            error_code="FORBIDDEN",
        )
