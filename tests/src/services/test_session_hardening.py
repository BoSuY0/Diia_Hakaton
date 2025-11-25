"""Tests for session field update hardening and validation."""
import pytest

from backend.domain.services.session import update_session_field
from backend.domain.services.fields import validate_session_readiness
from backend.infra.persistence.store import get_or_create_session, save_session
from backend.domain.sessions.models import FieldState, SessionState


def _base_session(session_id: str, category_id: str):
    s = get_or_create_session(session_id)
    s.category_id = category_id
    s.role = "lessor"
    s.person_type = "individual"
    s.party_types = {"lessor": "individual", "lessee": "individual"}
    save_session(s)
    return s


@pytest.mark.usefixtures("mock_settings", "mock_categories_data")
def test_update_session_field_requires_category():
    """Test that updating field requires category to be set."""
    s = get_or_create_session("no_cat_session")
    ok, err, fs = update_session_field(s, "name", "Some", role="lessor")
    assert ok is False
    assert "категорію" in err.lower()
    assert fs.status == "error"


@pytest.mark.usefixtures("mock_settings")
def test_update_session_field_requires_role_for_party_field(mock_categories_data):
    """Test that updating party field requires role to be set."""
    s = _base_session("need_role_session", mock_categories_data)
    s.role = None  # unset current role
    ok, err, fs = update_session_field(s, "name", "Some")
    assert ok is False
    assert "роль" in err.lower()
    assert fs.status == "error"


@pytest.mark.usefixtures("mock_settings")
def test_update_invalid_field_returns_error(mock_categories_data):
    """Test that updating unknown field returns error."""
    s = _base_session("unknown_field_session", mock_categories_data)
    ok, err, fs = update_session_field(s, "nonexistent_field", "Val", role="lessor")
    assert ok is False
    assert "не належить" in err.lower()
    assert fs.status == "error"


@pytest.mark.usefixtures("mock_settings")
def test_update_blocks_signed_role_and_invalidates_other_signatures(mock_categories_data):
    """Test that editing signed role is blocked and invalidates other signatures."""
    s = _base_session("sign_guard_session", mock_categories_data)
    s.signatures = {"lessor": True, "lessee": True}
    save_session(s)

    # Own signature present -> editing blocked
    ok, err, fs = update_session_field(s, "name", "New Name", role="lessor")
    assert ok is False
    assert "підписан" in err.lower()
    assert fs.status == "error"

    # Remove own signature but keep other -> editing should invalidate other signature
    s.signatures = {"lessor": False, "lessee": True}
    save_session(s)
    ok, err, fs = update_session_field(s, "name", "New Name", role="lessor")
    assert ok is True
    assert s.signatures.get("lessee") is False  # invalidated


@pytest.mark.usefixtures("mock_settings")
def test_validate_session_readiness_partial_vs_full(mock_categories_data):
    """Test session readiness validation in partial vs full mode."""
    # Full mode requires both roles
    s = _base_session("readiness_full", mock_categories_data)
    # Fill only lessor
    update_session_field(s, "name", "Lessor Name", role="lessor")
    update_session_field(s, "cf1", "Contract V", role=None)
    s.filling_mode = "full"
    ready_full = validate_session_readiness(s)
    assert ready_full is False

    # Partial mode with active role requires only its fields + contract
    s.filling_mode = "partial"
    s.role = "lessor"
    ready_partial = validate_session_readiness(s)
    assert ready_partial is True


@pytest.mark.usefixtures("mock_settings")
def test_update_session_field_sets_state_and_progress(mock_categories_data):
    """Test that field update sets session state and progress."""
    s = _base_session("progress_session", mock_categories_data)
    ok, _, fs = update_session_field(s, "cf1", "Val", role=None)
    assert ok is True
    assert s.contract_fields["cf1"].status == "ok"
    assert s.state in {SessionState.READY_TO_BUILD, SessionState.COLLECTING_FIELDS}
    assert s.progress.get("required_total") >= 1
    assert s.progress.get("required_filled") >= 1


@pytest.mark.usefixtures("mock_settings")
def test_update_session_field_history_and_current_on_error(mock_categories_data):
    """Test that invalid update preserves current value but logs in history."""
    s = _base_session("history_session", mock_categories_data)
    # First valid value sets current
    ok, _, _ = update_session_field(s, "cf1", "Valid", role=None)
    assert ok is True
    assert s.all_data["cf1"]["current"] == "Valid"
    # Invalid attempt should keep previous current but append history
    ok2, _, _ = update_session_field(s, "cf1", "", role=None)
    assert ok2 is False
    last = s.history[-1]
    assert last["type"] == "field_update"
    assert last["valid"] is False
    assert s.all_data["cf1"]["current"] == "Valid"


@pytest.mark.usefixtures("mock_settings")
def test_update_session_field_history_includes_actor(mock_categories_data):
    """Test that field update history includes actor information."""
    s = _base_session("history_actor_session", mock_categories_data)
    ok, _, _ = update_session_field(
        s,
        "cf1",
        "Valid",
        role=None,
        context={"user_id": "user1"},
    )
    assert ok is True
    entry = s.history[-1]
    assert entry["user_id"] == "user1"
    assert entry["role"] == "lessor"
    assert entry["ts"].endswith("Z") or entry["ts"].endswith("+00:00")
