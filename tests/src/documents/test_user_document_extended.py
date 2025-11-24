from backend.domain.documents.user_document import build_user_document
from backend.infra.persistence.store import get_or_create_session, save_session
from backend.domain.sessions.models import SessionState


def test_build_user_document_populates_fields(mock_settings, mock_categories_data):
    s = get_or_create_session("user_doc_session")
    s.category_id = mock_categories_data
    s.template_id = "t1"
    s.state = SessionState.BUILT
    s.party_types = {"lessor": "individual", "lessee": "company"}
    s.all_data = {
        "cf1": {"current": "CF"},
        "lessor.name": {"current": "Lessor"},
        "lessee.name": {"current": "Lessee LLC"},
    }
    save_session(s)

    doc = build_user_document(s)
    assert doc["status"] == "built"
    assert doc["contract_fields"]["cf1"] == "CF"
    assert doc["parties"]["lessor"]["person_type"] == "individual"
    assert doc["parties"]["lessee"]["person_type"] == "company"
    assert doc["parties"]["lessor"]["data"]["name"] == "Lessor"
    assert doc["parties"]["lessee"]["data"]["name"] == "Lessee LLC"


def test_build_user_document_defaults_roles_when_missing(mock_settings, mock_categories_data):
    s = get_or_create_session("user_doc_defaults")
    s.category_id = mock_categories_data
    s.all_data = {}
    save_session(s)

    doc = build_user_document(s)
    # Falls back to lessor/lessee with default person_type individual
    assert "lessor" in doc["parties"]
    assert doc["parties"]["lessor"]["person_type"] == "individual"
