import sys
from src.sessions.store import get_or_create_session, load_session
from src.agent.tools.session import SetPartyContextTool, UpsertFieldTool, GetPartyFieldsForSessionTool
from src.sessions.models import SessionState

def verify_multi_user():
    print("=== Verifying Multi-User Support ===")
    
    session_id = "test_multi_user_session"
    
    # 1. Create Session
    print(f"\n1. Creating session '{session_id}'...")
    session = get_or_create_session(session_id)
    session.category_id = "lease_living" # Assuming this category exists from previous steps or default
    session.save_session = lambda: None # Mock save for now? No, we need real save.
    # We rely on real store
    from src.sessions.store import save_session
    save_session(session)

    # Tools
    set_party_tool = SetPartyContextTool()
    upsert_tool = UpsertFieldTool()
    get_fields_tool = GetPartyFieldsForSessionTool()

    # 2. Set Context for Lessor (Individual)
    print("\n2. Setting context: Lessor (Individual)...")
    res = set_party_tool.execute({
        "session_id": session_id,
        "role": "lessor",
        "person_type": "individual"
    }, {})
    print(f"Result: {res}")
    
    # 3. Fill Lessor Name
    print("\n3. Filling Lessor Name -> 'Ivan Lessor'...")
    res = upsert_tool.execute({
        "session_id": session_id,
        "field": "name",
        "value": "Ivan Lessor"
    }, {})
    print(f"Result: {res}")

    # 4. Set Context for Lessee (Company)
    print("\n4. Setting context: Lessee (Company)...")
    res = set_party_tool.execute({
        "session_id": session_id,
        "role": "lessee",
        "person_type": "company"
    }, {})
    print(f"Result: {res}")

    # 5. Fill Lessee Name (Same field name 'name', but different role)
    print("\n5. Filling Lessee Name -> 'Mega Corp'...")
    res = upsert_tool.execute({
        "session_id": session_id,
        "field": "name",
        "value": "Mega Corp"
    }, {})
    print(f"Result: {res}")

    # 6. Verify Data Separation
    print("\n6. Verifying Data Separation...")
    session = load_session(session_id)
    
    lessor_name_state = session.party_fields.get("lessor", {}).get("name")
    lessee_name_state = session.party_fields.get("lessee", {}).get("name")
    
    print(f"Lessor Name State: {lessor_name_state}")
    print(f"Lessee Name State: {lessee_name_state}")

    lessor_val = session.all_data.get("lessor.name", {}).get("current")
    lessee_val = session.all_data.get("lessee.name", {}).get("current")

    print(f"Lessor Value (all_data): {lessor_val}")
    print(f"Lessee Value (all_data): {lessee_val}")

    if lessor_val == "Ivan Lessor" and lessee_val == "Mega Corp":
        print("\n[SUCCESS] Data is correctly separated by role!")
    else:
        print("\n[FAILURE] Data collision or missing values.")

    # 7. Verify Party Types
    print("\n7. Verifying Party Types...")
    print(f"Party Types: {session.party_types}")
    if session.party_types.get("lessor") == "individual" and session.party_types.get("lessee") == "company":
        print("[SUCCESS] Party types stored correctly.")
    else:
        print("[FAILURE] Party types mismatch.")

if __name__ == "__main__":
    verify_multi_user()
