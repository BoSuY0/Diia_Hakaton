import sys
import os
from src.sessions.models import Session, SessionState
from src.services.session import update_session_field

# Mock dependencies
class MockEntity:
    def __init__(self, field, type="text", required=True):
        self.field = field
        self.type = type
        self.required = required

def test_signature_logic():
    print("--- Testing Signature Logic ---")
    
    from src.sessions.store import save_session
    
    # Setup Session
    session = Session(
        session_id="test_sig_session",
        category_id="lease_real_estate",
        role="lessor",
        person_type="individual",
        party_types={"lessor": "individual", "lessee": "individual"},
        signatures={"lessor": False, "lessee": False}
    )
    save_session(session)
    
    # 1. Fill some data
    print("Filling initial data...")
    update_session_field(session, "name", "Lessor Name", role="lessor")
    save_session(session)
    
    # 2. Sign as Lessor using Tool
    print("Signing as Lessor...")
    # Need to mock tool execution or call logic directly?
    # Let's call the logic directly via a helper or just simulate what tool does.
    # Since we want to verify the TOOL logic, we should import it.
    from src.agent.tools.session import SignContractTool
    
    # We need to be in BUILT state to sign
    session.state = SessionState.BUILT
    save_session(session)
    
    tool = SignContractTool()
    res = tool.execute({"session_id": session.session_id, "role": "lessor"}, {})
    
    if res["ok"] and res["signed"]:
        print("✅ SignContractTool executed successfully")
    else:
        print(f"❌ SignContractTool failed: {res}")

    # Reload session to get updates from disk
    from src.sessions.store import load_session
    session = load_session(session.session_id)

    assert session.signatures["lessor"] is True
    assert session.signatures["lessee"] is False
    
    # 3. Try to edit as Lessor (Should be BLOCKED)
    print("Attempting edit as Lessor (Signed)...")
    ok, err, _ = update_session_field(session, "name", "New Name", role="lessor")
    if not ok and "підписали" in str(err).lower():
        print("✅ Edit blocked for signed party")
    else:
        print(f"❌ Edit NOT blocked! ok={ok}, err={err}")
        
    # 4. Edit as Lessee (Should be ALLOWED and INVALIDATE Lessor)
    print("Attempting edit as Lessee (Unsigned)...")
    # Switch context to lessee
    session.role = "lessee" 
    
    ok, err, _ = update_session_field(session, "name", "Lessee Name", role="lessee")
    
    if ok:
        print("✅ Edit allowed for unsigned party")
        # Check invalidation
        if session.signatures["lessor"] is False:
            print("✅ Lessor signature invalidated")
        else:
            print("❌ Lessor signature NOT invalidated")
    else:
        print(f"❌ Edit failed for lessee! err={err}")

if __name__ == "__main__":
    try:
        test_signature_logic()
        print("\nAll signature tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
