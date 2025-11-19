import sys
import logging
from uuid import uuid4
from src.app.server import ChatRequest, chat, on_startup
from src.common.logging import setup_logging

# Setup logging to see what's happening
setup_logging()
logger = logging.getLogger(__name__)

def run_test():
    print("=== Starting Verification Test ===")
    
    # 1. Initialize
    on_startup()
    session_id = f"test-session-{uuid4().hex[:8]}"
    print(f"Session ID: {session_id}")

    # 2. Test: Find Category
    print("\n--- Test Step 1: Find Category ---")
    req1 = ChatRequest(session_id=session_id, message="знайди договір оренди")
    try:
        resp1 = chat(req1)
        print(f"Bot Reply 1: {resp1.reply}")
        # We expect some mention of categories or templates
        if "оренд" in resp1.reply.lower() or "квартир" in resp1.reply.lower():
            print("✅ Step 1 Passed: Category/Template context found.")
        else:
            print("⚠️ Step 1 Warning: Unexpected response.")
    except Exception as e:
        print(f"❌ Step 1 Failed: {e}")
        return

    # 3. Test: Select Template (assuming the previous step listed some)
    # We'll try to be specific to trigger a template selection
    print("\n--- Test Step 2: Select Template ---")
    req2 = ChatRequest(session_id=session_id, message="обираю оренду квартири")
    try:
        resp2 = chat(req2)
        print(f"Bot Reply 2: {resp2.reply}")
        # If template is selected, it usually asks for fields
        if "поля" in resp2.reply.lower() or "fields" in resp2.reply.lower():
             print("✅ Step 2 Passed: Template selected, asking for fields.")
        else:
             print("⚠️ Step 2 Warning: Might not have selected template yet.")
    except Exception as e:
        print(f"❌ Step 2 Failed: {e}")
        return

    print("\n=== Verification Finished ===")

if __name__ == "__main__":
    run_test()
