import time
import threading
from concurrent.futures import ThreadPoolExecutor
from src.sessions.store import get_or_create_session, load_session

def worker(session_id, user_id):
    try:
        print(f"[{user_id}] Starting...")
        # Simulate slight delay to increase race chance
        time.sleep(0.01)
        session = get_or_create_session(session_id, user_id=user_id)
        print(f"[{user_id}] Done. Got session user: {session.user_id}")
        return session.user_id
    except Exception as e:
        print(f"[{user_id}] Error: {e}")
        return str(e)

def test_concurrency():
    print("--- Testing Concurrency (get_or_create_session) ---")
    session_id = f"conc_test_{int(time.time())}"
    num_threads = 5
    
    print(f"Launching {num_threads} threads for session {session_id}...")
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [
            executor.submit(worker, session_id, f"user_{i}")
            for i in range(num_threads)
        ]
        results = [f.result() for f in futures]
        
    print(f"Results: {results}")
    
    # Verify consistency
    # All results should be the SAME user_id (the one who won the race)
    # Because get_or_create_session returns existing session if found.
    
    # Find the winner (the user_id that was actually saved)
    # Note: results might contain different user_ids IF the race condition exists
    # and multiple threads overwrote each other.
    # But with locking, the first one creates, others read.
    
    unique_users = set(results)
    if len(unique_users) == 1:
        print(f"✅ Consistency check passed: All threads got the same session (User: {list(unique_users)[0]}).")
    else:
        print(f"❌ Consistency check FAILED: Threads got different sessions: {unique_users}")

    # Verify file content
    try:
        saved_session = load_session(session_id)
        print(f"Saved session user_id: {saved_session.user_id}")
        if saved_session.user_id in unique_users:
             print("✅ Saved session matches one of the results.")
        else:
             print("❌ Saved session has unexpected user_id!")
    except Exception as e:
        print(f"❌ Failed to load session: {e}")

if __name__ == "__main__":
    test_concurrency()
