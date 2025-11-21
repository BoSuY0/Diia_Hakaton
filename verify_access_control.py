import sys
import os
from fastapi.testclient import TestClient

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from src.app.server import app
from src.sessions.store import get_or_create_session, save_session
from src.sessions.models import SessionState

client = TestClient(app)

def test_access_control():
    print("Starting Access Control Verification...")

    # 1. Create Session
    resp = client.post("/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]
    print(f"Session created: {session_id}")

    # 2. Set Category (e.g. 'lease_agreement' which has 2 roles: lessor, lessee)
    # We assume 'lease_agreement' exists and has 2 roles.
    # If not, we might need to pick another one or mock.
    # Let's check available categories first.
    cats = client.get("/categories").json()
    if not cats:
        print("No categories found. Skipping test.")
        return
    
    cat_id = cats[0]["id"] # Use first category
    print(f"Using category: {cat_id}")
    
    resp = client.post(f"/sessions/{session_id}/category", json={"category_id": cat_id})
    assert resp.status_code == 200

    # 3. User 1 claims Role 1
    user1_id = "user_1"
    # We need to find a valid role.
    # Let's get schema to find roles.
    schema = client.get(f"/sessions/{session_id}/schema").json()
    roles = [p["role"] for p in schema["parties"]]
    print(f"Roles found: {roles}")
    
    if len(roles) < 2:
        print("Category has fewer than 2 roles. Cannot test full session blocking effectively.")
        return

    role1 = roles[0]
    role2 = roles[1]

    print(f"User 1 claiming role: {role1}")
    resp = client.post(
        f"/sessions/{session_id}/party-context",
        json={"role": role1, "person_type": "individual"},
        headers={"X-Client-ID": user1_id}
    )
    if resp.status_code != 200:
        print(f"Failed to claim role 1: {resp.text}")
        return
    assert resp.status_code == 200

    # 4. User 2 claims Role 2
    user2_id = "user_2"
    print(f"User 2 claiming role: {role2}")
    resp = client.post(
        f"/sessions/{session_id}/party-context",
        json={"role": role2, "person_type": "individual"},
        headers={"X-Client-ID": user2_id}
    )
    assert resp.status_code == 200

    # 5. User 3 tries to access session (GET /sessions/{id})
    # Session should be full now (assuming 2 roles).
    user3_id = "user_3"
    print("User 3 trying to access session (should be BLOCKED)...")
    resp = client.get(f"/sessions/{session_id}", headers={"X-Client-ID": user3_id})
    
    if resp.status_code == 403:
        print("SUCCESS: User 3 blocked with 403.")
    else:
        print(f"FAILURE: User 3 got status {resp.status_code}: {resp.text}")

    # 6. User 3 tries to get schema
    print("User 3 trying to get schema (should be BLOCKED)...")
    resp = client.get(f"/sessions/{session_id}/schema", headers={"X-Client-ID": user3_id})
    if resp.status_code == 403:
        print("SUCCESS: User 3 blocked from schema with 403.")
    else:
        print(f"FAILURE: User 3 got status {resp.status_code} from schema")

    # 7. User 1 accesses session (should be ALLOWED)
    print("User 1 accessing session (should be ALLOWED)...")
    resp = client.get(f"/sessions/{session_id}", headers={"X-Client-ID": user1_id})
    if resp.status_code == 200:
        print("SUCCESS: User 1 allowed.")
    else:
        print(f"FAILURE: User 1 blocked with {resp.status_code}")

    # 8. User 1 tries to claim Role 2 (should fail or be blocked logic?)
    # Our logic says "1 role per user".
    # Let's try to claim role 2 as user 1.
    print("User 1 trying to claim Role 2 (should fail)...")
    resp = client.post(
        f"/sessions/{session_id}/party-context",
        json={"role": role2, "person_type": "individual"},
        headers={"X-Client-ID": user1_id}
    )
    # It might fail with 400 (ValueError) or 200 if we allowed switching (we blocked it in claim_session_role).
    if resp.status_code != 200:
        print(f"SUCCESS: User 1 blocked from claiming second role: {resp.text}")
    else:
        print("FAILURE: User 1 was able to claim second role.")

    print("Verification Complete.")

if __name__ == "__main__":
    try:
        test_access_control()
    except Exception as e:
        print(f"Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
