import pytest
from unittest.mock import patch

from src.documents.builder import build_contract
from src.sessions.store import get_or_create_session, save_session
from src.sessions.models import FieldState
from src.common.errors import MetaNotFoundError


def _base_session(session_id: str, cat_id: str, templ_id: str):
    s = get_or_create_session(session_id)
    s.category_id = cat_id
    s.template_id = templ_id
    s.party_types = {"lessor": "individual"}
    # Required fields from mock_categories_data: cf1 + lessor.name
    s.contract_fields["cf1"] = FieldState(status="ok")
    s.party_fields["lessor"] = {"name": FieldState(status="ok")}
    s.all_data["cf1"] = {"current": "V"}
    s.all_data["lessor.name"] = {"current": "Name"}
    save_session(s)
    return s


def test_build_contract_missing_category_raises(mock_settings):
    with pytest.raises(MetaNotFoundError):
        build_contract("unknown_session", "any")


def test_build_contract_wrong_template(mock_settings, mock_categories_data):
    s = _base_session("wrong_template", mock_categories_data, "t1")
    with pytest.raises(MetaNotFoundError):
        build_contract(s.session_id, "foreign")


def test_build_contract_partial_mode_allows_missing(mock_settings, mock_categories_data, monkeypatch, tmp_path):
    s = _base_session("partial_build", mock_categories_data, "t1")
    # Remove a required field
    s.contract_fields["cf1"].status = "empty"
    s.all_data["cf1"] = {"current": ""}
    save_session(s)

    # Patch VALUES: create dummy template file
    template_path = tmp_path / "assets" / "documents" / "default_documents_files" / mock_categories_data / "f1.docx"
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.touch()
    monkeypatch.setattr("src.documents.builder.settings.default_documents_root", template_path.parent.parent)

    # Patch fill_docx_template to avoid docx processing
    with patch("src.documents.builder.fill_docx_template") as filler:
        res = build_contract(s.session_id, "t1", partial=True)
        assert res["file_path"]  # returns path even with missing required because partial=True
        filler.assert_called_once()


def test_build_contract_requires_fields_when_not_partial(mock_settings, mock_categories_data):
    s = _base_session("missing_required", mock_categories_data, "t1")
    s.contract_fields["cf1"].status = "empty"
    save_session(s)
    with pytest.raises(ValueError):
        build_contract(s.session_id, "t1")
