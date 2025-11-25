"""Tests for authentication headers handling."""
import pytest
import jwt
from fastapi.testclient import TestClient

from backend.api.http.server import app
from backend.infra.config.settings import settings
from backend.infra.persistence.store import get_or_create_session, save_session
from backend.domain.sessions.models import SessionState


client = TestClient(app)


def _prepare_session(session_id: str, category_id: str) -> None:
    session = get_or_create_session(session_id)
    session.category_id = category_id
    session.template_id = "t1"
    session.party_types = {"lessor": "individual", "lessee": "individual"}
    session.state = SessionState.TEMPLATE_SELECTED
    save_session(session)


@pytest.mark.usefixtures("mock_settings")
def test_bearer_jwt_allows_access(mock_categories_data):
    """Test that Bearer JWT token allows access."""
    settings.auth_mode = "jwt"
    settings.auth_jwt_secret = "secret-key"
    token = jwt.encode(
        {"sub": "jwt-user"}, settings.auth_jwt_secret, algorithm=settings.auth_jwt_algorithm
    )

    _prepare_session("jwt-session", mock_categories_data)
    resp = client.get(
        "/sessions/jwt-session/schema",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("session_id") == "jwt-session"


@pytest.mark.usefixtures("mock_settings")
def test_jwt_mode_rejects_header_only(mock_categories_data):
    """Test that JWT mode rejects X-User-ID header only."""
    settings.auth_mode = "jwt"
    settings.auth_jwt_secret = "secret-key"

    _prepare_session("jwt-only", mock_categories_data)
    resp = client.get(
        "/sessions/jwt-only/schema",
        headers={"X-User-ID": "header-user"},
    )

    assert resp.status_code == 401
    assert "bearer token" in resp.json().get("detail", "").lower()
