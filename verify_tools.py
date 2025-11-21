
import sys
import os
sys.path.append(os.getcwd())

from src.agent.tools.get_category_roles_tool import get_category_roles_tool
from src.agent.tools.set_party_context_tool import set_party_context_tool
from src.sessions.store import get_or_create_session, save_session
from src.sessions.models import SessionState

def test_tools():
    session_id = "test_session_tools"
    session = get_or_create_session(session_id)
    session.category_id = "lease_living"
    session.state = SessionState.CATEGORY_SELECTED
    save_session(session)

    print("Testing get_category_roles...")
    roles = get_category_roles_tool({"category_id": "lease_living"}, {})
    print(f"Roles: {roles}")
    if "roles" not in roles:
        print("FAIL: roles not found")
        return

    print("\nTesting set_party_context...")
    res = set_party_context_tool({
        "session_id": session_id,
        "role": "lessee",
        "person_type": "individual"
    }, {})
    print(f"Result: {res}")
    
    if not res.get("ok"):
        print(f"FAIL: {res.get('error')}")
        return

    session = get_or_create_session(session_id)
    if session.role == "lessee" and session.person_type == "individual":
        print("SUCCESS: Party context set correctly")
    else:
        print("FAIL: Session not updated correctly")

if __name__ == "__main__":
    test_tools()
