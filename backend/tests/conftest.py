"""
tests/conftest.py

Responsibility
--------------
Shared pytest fixtures for the whole test suite. This milestone only
needs a `client` fixture (a FastAPI `TestClient` wired to the real app
factory), but this is the established location for fixtures every future
test file will reuse — e.g. a DB-transaction-per-test fixture and a
fake-authenticated-user fixture, added when the auth module lands.

Note: this milestone's tests do not touch the database or Redis at all
(the health endpoint has no dependencies), so no DB fixtures are defined
yet — adding them now would be scope creep the milestone instructions
explicitly disallow.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    """Returns a TestClient built from a freshly constructed app instance
    (via the app factory), so each test gets an isolated app object
    rather than importing the module-level `app` singleton directly."""
    app = create_app()
    return TestClient(app)
