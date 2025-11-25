"""Hardening tests for contract builder."""
from unittest.mock import patch

import pytest

from backend.domain.documents.builder import build_contract
from backend.infra.persistence.store import get_or_create_session, save_session
from backend.domain.sessions.models import FieldState
from backend.shared.errors import MetaNotFoundError


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


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_build_contract_missing_category_raises():
    """Test that building contract without category raises error."""
    with pytest.raises(MetaNotFoundError):
        await build_contract("unknown_session", "any")


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_build_contract_wrong_template(mock_categories_data):
    """Test that building contract with wrong template raises error."""
    s = _base_session("wrong_template", mock_categories_data, "t1")
    with pytest.raises(MetaNotFoundError):
        await build_contract(s.session_id, "foreign")


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_build_contract_partial_mode_allows_missing(
    mock_categories_data, monkeypatch, tmp_path
):
    """Test that partial mode allows building with missing fields."""
    s = _base_session("partial_build", mock_categories_data, "t1")
    # Remove a required field
    s.contract_fields["cf1"].status = "empty"
    s.all_data["cf1"] = {"current": ""}
    save_session(s)

    # Patch VALUES: create dummy template file
    cat_path = mock_categories_data
    template_path = (
        tmp_path / "assets" / "documents" / "default_documents_files" / cat_path / "f1.docx"
    )
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.touch()
    monkeypatch.setattr(
        "backend.domain.documents.builder.settings.default_documents_root",
        template_path.parent.parent
    )

    # Patch fill_docx_template to avoid docx processing
    with patch("backend.domain.documents.builder.fill_docx_template") as filler:
        res = await build_contract(s.session_id, "t1", partial=True)
        assert res["file_path"]  # returns path even with missing required because partial=True
        filler.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_settings")
async def test_build_contract_requires_fields_when_not_partial(mock_categories_data):
    """Test that building contract requires all fields when not partial."""
    s = _base_session("missing_required", mock_categories_data, "t1")
    s.contract_fields["cf1"].status = "empty"
    save_session(s)
    with pytest.raises(ValueError):
        await build_contract(s.session_id, "t1")
