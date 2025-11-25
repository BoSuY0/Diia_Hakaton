import pytest
from unittest.mock import patch, MagicMock
from backend.domain.documents.builder import build_contract
from backend.infra.persistence.store import get_or_create_session, save_session
from backend.domain.sessions.models import FieldState

@pytest.fixture
def ready_session(mock_settings, mock_categories_data):
    session_id = "builder_test_session"
    s = get_or_create_session(session_id)
    s.category_id = "test_cat"
    s.template_id = "t1"
    s.role = "lessor"
    s.person_type = "individual"

    # Set contract fields
    s.contract_fields["cf1"] = FieldState(status="ok")
    s.all_data["cf1"] = {"current": "Contract Val"}

    # Set party fields
    s.party_fields["lessor"] = {"name": FieldState(status="ok")}
    s.all_data["lessor.name"] = {"current": "Lessor Name"}

    s.party_fields["lessee"] = {"name": FieldState(status="ok")}
    s.all_data["lessee.name"] = {"current": "Lessee Name"}

    # Set party types
    s.party_types["lessor"] = "individual"
    s.party_types["lessee"] = "individual"

    save_session(s)
    return session_id

@pytest.mark.asyncio
async def test_build_contract_success(ready_session, mock_settings):
    # Mock fill_docx_template to avoid needing a real docx file
    with patch("backend.domain.documents.builder.fill_docx_template") as mock_fill:
        # Also ensure the template file check passes
        # The builder checks if template exists.
        # mock_categories_data creates the meta, but maybe not the file?
        # Let's create a dummy file
        template_path = mock_settings.default_documents_root / "test_cat" / "f1.docx"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.touch()

        res = await build_contract(ready_session, "t1")

        assert res["filename"].endswith(".docx")
        assert "application/vnd.openxmlformats" in res["mime"]

        # Verify arguments passed to filler
        args, _ = mock_fill.call_args
        template_arg, values_arg, output_arg = args

        assert str(template_arg) == str(template_path)
        assert values_arg["cf1"] == "Contract Val"
        assert values_arg["lessor.name"] == "Lessor Name"

@pytest.mark.asyncio
async def test_build_contract_missing_field(ready_session):
    # Invalidate a field
    from backend.infra.persistence.store import load_session
    s = load_session(ready_session)
    s.contract_fields["cf1"].status = "empty"
    save_session(s)

    with pytest.raises(ValueError, match="Missing required fields"):
        await build_contract(ready_session, "t1")

@pytest.mark.asyncio
async def test_build_contract_wrong_template(ready_session):
    with pytest.raises(Exception, match="Template in session does not match"):
        from backend.shared.errors import MetaNotFoundError
        try:
            await build_contract(ready_session, "t2")
        except MetaNotFoundError as e:
            raise Exception(str(e))
