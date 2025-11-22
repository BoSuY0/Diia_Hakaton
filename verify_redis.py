#!/usr/bin/env python3
"""
Quick Redis connection verification script.
Tests basic Redis operations to ensure connectivity.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.common.logging import get_logger
from src.storage.redis_client import get_redis

logger = get_logger(__name__)


def verify_redis() -> bool:
    """Verify Redis connection and basic operations."""
    print("\n" + "=" * 50)
    print("🔍 Redis Connection Verification")
    print("=" * 50 + "\n")
    
    try:
        # Get Redis client
        print("📡 Connecting to Redis...")
        client = get_redis()
        
        # Test 1: Ping
        print("1️⃣  Testing PING...", end=" ")
        response = client.ping()
        if response:
            print("✅ Success")
        else:
            print("❌ Failed")
            return False
        
        # Test 2: Set/Get
        print("2️⃣  Testing SET/GET...", end=" ")
        test_key = "test:verification"
        test_value = "Redis is working!"
        client.set(test_key, test_value, ex=10)
        retrieved = client.get(test_key)
        if retrieved == test_value:
            print("✅ Success")
        else:
            print(f"❌ Failed (expected '{test_value}', got '{retrieved}')")
            return False
        
        # Test 3: TTL
        print("3️⃣  Testing TTL...", end=" ")
        ttl = client.ttl(test_key)
        if ttl > 0:
            print(f"✅ Success (expires in {ttl}s)")
        else:
            print(f"⚠️  Unexpected TTL: {ttl}")
        
        # Test 4: Delete
        print("4️⃣  Testing DELETE...", end=" ")
        deleted = client.delete(test_key)
        print("✅ Success" if deleted else "⚠️  Key not found")
        
        # Test 5: Sorted Set (used for sessions)
        print("5️⃣  Testing ZADD/ZRANGE...", end=" ")
        zset_key = "test:sorted_set"
        client.zadd(zset_key, {"item1": 1.0, "item2": 2.0})
        items = client.zrevrange(zset_key, 0, -1)
        client.delete(zset_key)
        if items == ["item2", "item1"]:
            print("✅ Success")
        else:
            print(f"⚠️  Unexpected result: {items}")
        
        print("\n" + "=" * 50)
        print("🎉 All tests passed! Redis is working correctly!")
        print("=" * 50 + "\n")
        return True
        
    except ConnectionError as e:
        print(f"\n❌ Connection Error: {e}\n")
        print("💡 Troubleshooting:")
        print("   • Check REDIS_URL in .env")
        print("   • For AWS: Verify security group allows port 6379")
        print("   • For AWS: Ensure you're in the same VPC")
        print("   • For local: Ensure Redis is running (docker-compose up)")
        return False
        
    except Exception as e:
        print(f"\n❌ Error: {type(e).__name__}: {e}\n")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv()
    
    # Show configuration (redacted)
    redis_url = os.getenv("REDIS_URL", "NOT SET")
    if redis_url and redis_url != "NOT SET":
        # Redact sensitive parts
        if "@" in redis_url:
            parts = redis_url.split("@")
            redis_url_display = f"{parts[0].split('://')[0]}://***@{parts[1]}"
        else:
            # Show protocol and host only
            try:
                from urllib.parse import urlparse
                parsed = urlparse(redis_url)
                redis_url_display = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 6379}"
            except:
                redis_url_display = redis_url
        print(f"📝 REDIS_URL: {redis_url_display}")
    else:
        print("⚠️  REDIS_URL is not set in .env file!")
        sys.exit(1)
    
    print(f"📝 USE_VALKEY_GLIDE: {os.getenv('USE_VALKEY_GLIDE', 'false')}")
    
    # Run verification
    success = verify_redis()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)

