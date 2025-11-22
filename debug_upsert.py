import sys
import os
import json

# Add project root to path
sys.path.append(os.getcwd())

from src.agent.tools.upsert_field_tool import upsert_field_tool
from src.sessions.store import get_or_create_session

session_id = "demo-session-1"
# Ensure session exists and has correct state (it should from previous steps)
session = get_or_create_session(session_id)
print(f"Session category: {session.category_id}")
print(f"Session role: {session.role}")
print(f"Session person_type: {session.person_type}")

args = {
    "session_id": session_id,
    "field": "id_code",
    "value": "3124567891",
    "role": "receiving_party"
}
context = {"tags": {}}

print("Calling upsert_field_tool...")
result = upsert_field_tool(args, context)
print(json.dumps(result, indent=2, ensure_ascii=False))
