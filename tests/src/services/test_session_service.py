"""Tests for session service functions."""
import pytest

from backend.domain.services.session import set_party_type
from backend.infra.persistence.store import get_or_create_session, save_session
from backend.domain.sessions.models import FieldState, SessionState


@pytest.mark.usefixtures("mock_settings", "mock_categories_data")
def test_set_party_type_invalidates_signature():
    """Test that changing party type invalidates signature and clears fields."""
    session = get_or_create_session("sig_reset")
    session.category_id = "test_cat"

    # Початковий тип та заповнені поля для ролі, підпис уже виставлено
    session.party_types["lessor"] = "individual"
    session.party_fields["lessor"] = {"name": FieldState(status="ok")}
    session.all_data["lessor.name"] = {"current": "John Doe"}
    session.signatures["lessor"] = True
    session.state = SessionState.READY_TO_SIGN
    save_session(session)

    # Змінюємо тип особи
    set_party_type(session, "lessor", "company")

    assert session.party_types["lessor"] == "company"
    assert session.party_fields["lessor"] == {}
    assert "lessor.name" not in session.all_data
    assert session.signatures.get("lessor") is False

    # Після зміни типу дані не валідні, сесія має втратити готовність
    assert session.can_build_contract is False
    assert session.state in {SessionState.COLLECTING_FIELDS, SessionState.READY_TO_BUILD}
