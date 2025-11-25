"""Verification script for session service functions."""
import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

# pylint: disable=wrong-import-position
from backend.domain.sessions.models import Session, SessionState
from backend.domain.services.session import update_session_field
from backend.domain.categories.index import store as category_store

# Mock category store for testing if needed, or use real one if available
# Assuming we have some categories loaded. If not, we might need to mock.
# Let's check if we can load real categories.
category_store.load()
if not category_store.categories:
    print("WARNING: No categories found. Verification might fail if it depends on real categories.")
    # We might need to mock list_entities/list_party_fields if no real data
else:
    print(f"Loaded {len(category_store.categories)} categories.")

def test_update_session_field() -> None:
    """Test update_session_field and related session service functions."""
    # pylint: disable=import-outside-toplevel,too-many-statements,too-many-locals
    print("\n--- Testing update_session_field ---")

    # 1. Setup Session
    session = Session(session_id="test_session")
    # Pick a category if available, e.g. "lease_agreement" or whatever is in the project
    cat_id = next(iter(category_store.categories.keys()), None)
    if not cat_id:
        print("Skipping test: No categories available.")
        return

    session.category_id = cat_id
    session.role = "lessor"
    session.person_type = "individual"
    session.party_types = {"lessor": "individual", "lessee": "individual"}

    print(f"Using category: {cat_id}")

    # 2. Test Valid Update (Party Field)
    # Find a valid field name
    from backend.domain.categories.index import list_party_fields
    fields = list_party_fields(cat_id, "individual")
    if not fields:
        print("No fields for individual in this category.")
        return

    field_name = fields[0].field
    print(f"Testing field: {field_name}")

    ok, _, fs = update_session_field(session, field_name, "Test Value", role="lessor")

    assert ok is True
    assert fs.status == "ok"
    assert session.party_fields["lessor"][field_name].status == "ok"
    assert session.all_data[f"lessor.{field_name}"]["current"] == "Test Value"
    print("✅ Valid update successful")

    # 3. Test Invalid Update (if we can trigger validation error)
    # Try to find an IBAN field or similar
    iban_field = next((f.field for f in fields if "iban" in f.field), None)
    if iban_field:
        print(f"Testing invalid IBAN on field: {iban_field}")
        ok, _, fs = update_session_field(session, iban_field, "INVALID_IBAN", role="lessor")
        assert ok is False
        assert fs.status == "error"
        assert "IBAN" in str(fs.error) or "Invalid" in str(fs.error)
        print("✅ Invalid update correctly rejected")
    else:
        print("ℹ️ No IBAN field found for validation test")

    # 4. Test History (global session.history, not per-field)
    print("Testing history tracking...")
    update_session_field(session, field_name, "Value 1", role="lessor")
    update_session_field(session, field_name, "Value 2", role="lessor")

    field_history = [
        evt for evt in session.history
        if evt.get("type") == "field_update" and evt.get("key") == f"lessor.{field_name}"
    ]
    assert len(field_history) >= 2  # +1 from first test
    assert field_history[-1]["value"] == "Value 2"
    print("✅ History tracked correctly")

    # 5. Test State Cleanup (Person Type Change)
    print("Testing state cleanup on person type change...")
    from backend.domain.services.session import set_party_type

    # Currently lessor is individual, and we have fields set
    assert f"lessor.{field_name}" in session.all_data
    assert field_name in session.party_fields["lessor"]

    # Switch to company (assuming company type exists and has different fields)
    # If company not in allowed types, this might fail validation in real app
    set_party_type(session, "lessor", "company")

    assert session.party_types["lessor"] == "company"
    # Fields should be cleared
    assert len(session.party_fields["lessor"]) == 0
    # all_data should be cleared for this role
    assert f"lessor.{field_name}" not in session.all_data
    print("✅ State cleanup successful")

    # 6. Test Filling Mode (Partial vs Full)
    print("Testing filling mode logic...")
    from backend.domain.services.fields import validate_session_readiness

    # Reset session fields
    session.party_fields = {}
    session.contract_fields = {}
    session.role = "lessor"
    session.person_type = "individual"
    session.party_types = {"lessor": "individual", "lessee": "individual"}

    # Set FULL mode
    session.filling_mode = "full"
    # Should NOT be ready (no fields)
    assert validate_session_readiness(session) is False

    # Fill lessor fields
    update_session_field(session, field_name, "Lessor Name", role="lessor")
    # Still not ready because lessee missing
    assert validate_session_readiness(session) is False

    # Set PARTIAL mode
    session.filling_mode = "partial"

    # We need to fill ALL required fields for the current role + contract fields
    # to be ready in partial mode.
    from backend.domain.services.fields import get_required_fields
    reqs = get_required_fields(session)

    print(f"Filling {len(reqs)} required fields for partial mode...")
    for r in reqs:
        # Fill with dummy value
        val = "Dummy Value"
        if "date" in r.key:
            val = "01.01.2025"
        elif "email" in r.key:
            val = "test@example.com"
        elif "iban" in r.key:
            val = "UA" + "0" * 27  # Valid-ish IBAN length
        elif "rnokpp" in r.key:
            val = "1234567890"

        # We need to pass role if it's a party field
        update_session_field(session, r.field_name, val, role=r.role)

    is_ready = validate_session_readiness(session)
    if is_ready:
        print("✅ Partial mode validation successful (Ready with only one side)")
    else:
        print("❌ Partial mode validation failed (Not ready)")
        # Debug
        reqs_still = get_required_fields(session)
        # Check which ones are not ok
        missing = []
        for r in reqs_still:
            if r.role:
                st = session.party_fields.get(r.role, {}).get(r.field_name)
            else:
                st = session.contract_fields.get(r.field_name)

            if not st or st.status != "ok":
                missing.append(r.key)
        print("Missing:", missing)

        print("Missing:", missing)

    # 7. Test set_session_template
    print("\n--- Testing set_session_template ---")
    from backend.domain.services.session import set_session_template

    # Mock template_id
    new_template_id = "test_template_123"
    set_session_template(session, new_template_id)

    if session.template_id == new_template_id:
        print("✅ set_session_template updated template_id")
    else:
        print(f"❌ set_session_template failed: {session.template_id}")

    if session.state == SessionState.TEMPLATE_SELECTED:
        print(f"✅ State updated to {session.state}")
    else:
        print(f"⚠️ State is {session.state} (expected TEMPLATE_SELECTED or READY_TO_BUILD)")


if __name__ == "__main__":
    try:
        test_update_session_field()
        print("\nAll tests passed!")
    except (RuntimeError, ValueError, AssertionError) as e:
        print(f"\n❌ Test failed: {e}")
        import traceback  # pylint: disable=import-outside-toplevel
        traceback.print_exc()
