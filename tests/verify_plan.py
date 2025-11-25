"""Verification tests for PII persistence, role upsert, and contract API flow."""
import json
import os
import sys
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.getcwd())

from backend.api.http.state import conversation_store  # pylint: disable=wrong-import-position
from backend.infra.persistence.store import load_session, save_session  # pylint: disable=wrong-import-position
from tests.test_utils import (  # pylint: disable=wrong-import-position
    setup_mock_chat,
    create_mock_chat_response,
)

patcher, mock_chat, client = setup_mock_chat()
mock_response = create_mock_chat_response()
mock_chat.return_value = mock_response
USER_ID = "plan_user"

def test_pii_persistence() -> None:
    """Test PII persistence and unmasking in conversation tags."""
    print("\n--- Testing PII Persistence ---")
    # 1. Create session
    resp = client.post("/sessions", json={}, headers={"X-User-ID": USER_ID})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]
    print(f"Session created: {session_id}")

    # 2. Send message with PII
    fake_iban = "UA213223130000026007233566001"
    msg1 = f"Мій IBAN {fake_iban}"
    resp = client.post(
        "/chat",
        json={"session_id": session_id, "message": msg1},
        headers={"X-User-ID": USER_ID},
    )
    assert resp.status_code == 200

    # Check if PII was captured in conversation store
    conv = conversation_store.get(session_id)
    print(f"Stored tags: {conv.tags}")

    # Find the tag for our IBAN
    iban_tag = None
    for tag, value in conv.tags.items():
        if value.strip() == fake_iban:
            iban_tag = tag
            break

    assert iban_tag is not None, "IBAN not captured in tags"
    print(f"Found tag {iban_tag} for IBAN")

    # 3. Simulate LLM using the tag in a later turn
    # We will mock the LLM response to call upsert_field with the tag

    # First, setup context so upsert_field is allowed
    client.post(
        f"/sessions/{session_id}/category",
        json={"category_id": "lease_real_estate"},
        headers={"X-User-ID": USER_ID},
    )
    client.post(
        f"/sessions/{session_id}/template",
        json={"template_id": "lease_flat"},
        headers={"X-User-ID": USER_ID},
    )
    client.post(
        "/chat",
        json={"session_id": session_id, "message": "set role to lessor"},
        headers={"X-User-ID": USER_ID},
    )

    # Mock LLM to call upsert_field with the tag
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_123"
    mock_tool_call.function.name = "upsert_field"
    mock_tool_call.function.arguments = json.dumps({
        "field": "id_code", # Using id_code just for test, though it expects digits usually. 
                            # But upsert_field unmasks BEFORE validation.
                            # If validation fails, it's fine, as long as we see unmasking happened.
                            # But better to use a field that accepts text or match the type.
                            # IBAN is usually for bank details.
        "value": iban_tag
    })

    mock_response.choices[0].message.tool_calls = [mock_tool_call]

    # Send a dummy message to trigger the tool loop
    resp = client.post(
        "/chat",
        json={"session_id": session_id, "message": "use my iban"},
        headers={"X-User-ID": USER_ID},
    )
    assert resp.status_code == 200

    # Check if the field was upserted with the REAL value (unmasked)
    # We check session.party_fields or all_data
    session = load_session(session_id)

    # We tried to upsert 'id_code' with the IBAN value.
    # Check session.party_fields['lessor']['id_code']
    # Or check session.all_data['id_code']

    # Note: upsert_field stores in all_data
    # But wait, id_code validation might fail for IBAN format.
    # Let's check if it failed but stored the raw value in history?

    # Let's look at all_data
    print("All Data keys:", session.all_data.keys())
    # Check global history for unmasked value
    entries = [
        e for e in session.history
        if e.get("type") == "field_update" and e.get("key") in ("lessor.id_code", "id_code")
    ]
    assert entries, "No history events for id_code"
    last_entry = entries[-1]
    print(f"Last history entry: {last_entry}")
    expected_val = fake_iban
    actual_val = last_entry.get("value")
    assert actual_val == expected_val, f"Expected {expected_val}, got {actual_val}"
    print("PII Unmasking: OK")

    # Reset mock
    mock_response.choices[0].message.tool_calls = []


def test_explicit_role_upsert() -> None:
    """Test explicit role upsert with different active role."""
    print("\n--- Testing Explicit Role Upsert ---")
    # 1. Create session
    resp = client.post("/sessions", json={}, headers={"X-User-ID": USER_ID})
    session_id = resp.json()["session_id"]

    # 2. Setup Category and Template
    client.post(
        f"/sessions/{session_id}/category",
        json={"category_id": "lease_real_estate"},
        headers={"X-User-ID": USER_ID},
    )
    client.post(
        f"/sessions/{session_id}/template",
        json={"template_id": "lease_flat"},
        headers={"X-User-ID": USER_ID},
    )

    # 3. Define Party Types (REQUIRED before upserting party fields)
    # Manually set party types in session store since we are mocking LLM

    session = load_session(session_id)
    session.party_types = {
        "lessee": "individual",
        "lessor": "individual"
    }
    # Set active role to lessor to prove we can write to lessee explicitly
    session.role = "lessor"
    session.person_type = "individual"
    save_session(session)

    # Now session.role is 'lessor'.

    # 4. Upsert field for 'lessee' explicitly (while active role is 'lessor')
    print("Upserting field 'name' for 'lessee' (explicitly)...")
    resp = client.post(
        f"/sessions/{session_id}/fields",
        json={
            "field": "name",
            "value": "Lessee Explicit Name",
            "role": "lessee"
        },
    )
    if resp.status_code != 200:
        print(f"FAILED: {resp.text}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True

    # 5. Verify data is stored correctly in all_data under 'lessee.name'
    session = load_session(session_id)
    all_data = session.all_data

    # Check if 'lessee.name' exists and has the correct value
    entry = all_data.get("lessee.name")
    assert entry is not None, "Entry 'lessee.name' not found in all_data"
    expected = "Lessee Explicit Name"
    assert entry["current"] == expected, f"Expected '{expected}', got {entry['current']}"

    # Check if 'lessor.name' is NOT affected (it should be empty or different)
    lessor_entry = all_data.get("lessor.name")
    lessor_not_affected = lessor_entry is None or lessor_entry.get("current") != expected
    assert lessor_not_affected, "Lessor name incorrectly updated"

    print("Explicit role upsert verified successfully.")


def test_contract_api_flow() -> None:
    """Test contract API flow: create, preview, sign, download."""
    print("\n--- Testing Contract API Flow ---")
    # 1. Setup Session
    resp = client.post("/sessions", json={}, headers={"X-User-ID": USER_ID})
    session_id = resp.json()["session_id"]
    user_id = "plan_user"

    # 2. Sync Session to be ready
    sync_data = {
        "category_id": "lease_real_estate",
        "template_id": "lease_flat",
        "parties": {
            "lessor": {
                "person_type": "individual",
                "fields": {
                    "name": "Ivanov",
                    "address": "Kyiv",
                    "id_code": "1234567890",
                    "id_doc": "AB123456"
                }
            },
            "lessee": {
                "person_type": "individual",
                "fields": {
                    "name": "Petrov",
                    "address": "Lviv",
                    "id_code": "0987654321",
                    "id_doc": "CD654321"
                }
            }
        }
    }
    client.post(
        f"/sessions/{session_id}/sync",
        json=sync_data,
        headers={"X-User-ID": user_id},
    )

    # Upsert remaining contract fields
    contract_fields = {
        "object_address": "Kyiv, Main St, 1",
        "rent_price_month": "10000",
        "start_date": "01.01.2025"
    }
    for f, v in contract_fields.items():
        client.post(
            f"/sessions/{session_id}/fields",
            json={"field": f, "value": v},
            headers={"X-User-ID": user_id},
        )

    # Force can_build_contract just in case
    sess = load_session(session_id)
    sess.can_build_contract = True
    save_session(sess)

    # 3. Get Contract Info
    resp = client.get(
        f"/sessions/{session_id}/contract",
        headers={"X-User-ID": user_id},
    )
    data = resp.json()
    print("Contract Info:", data)
    assert data["is_signed"] is False
    assert data["can_build_contract"] is True
    assert data["preview_url"].startswith(f"/sessions/{session_id}/contract/preview")
    # document_url should be None or present?
    # Code: "document_url": ... if session.state == "built" else None
    # State is probably READY_TO_BUILD, not BUILT yet.

    # 4. Preview
    resp = client.get(
        f"/sessions/{session_id}/contract/preview",
        headers={"X-User-ID": user_id},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")

    # Now state might be BUILT because preview calls build_contract if needed?
    # Let's check code:
    # if not path.exists(): if can_build: tool_build_contract(...)
    # tool_build_contract sets state to BUILT.

    resp = client.get(
        f"/sessions/{session_id}/contract",
        headers={"X-User-ID": user_id},
    )
    data = resp.json()
    assert data["document_ready"] is True
    assert data["document_url"].startswith(f"/sessions/{session_id}/contract/download")

    # 5. Download (Unsigned) -> 403
    resp = client.get(
        f"/sessions/{session_id}/contract/download",
        headers={"X-User-ID": user_id},
    )
    assert resp.status_code == 403

    # 6. Sign
    resp = client.post(
        f"/sessions/{session_id}/contract/sign",
        headers={"X-User-ID": user_id},
    )
    assert resp.status_code == 200
    assert resp.json()["is_signed"] is True

    # 7. Download (Signed) -> 200
    resp = client.get(
        f"/sessions/{session_id}/contract/download",
        headers={"X-User-ID": user_id},
    )
    print(f"Download (Signed) Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Download Error: {resp.text}")
    assert resp.status_code == 200
    print("Contract API Flow: OK")

if __name__ == "__main__":
    try:
        test_pii_persistence()
        test_explicit_role_upsert()
        test_contract_api_flow()
        print("\nALL TESTS PASSED")
    except (RuntimeError, ValueError, AssertionError) as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
