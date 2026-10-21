#!/usr/bin/env python3
"""
Direct test script for the Precision RAG AI Reviewer service.
Can test either via HTTP endpoint or by invoking the local pipeline directly.
"""

import sys
import json
import httpx

AI_SERVICE_URL = "http://localhost:8000"

SAMPLE_DIFF = """--- a/src/auth.py
+++ b/src/auth.py
@@ -14,5 +14,6 @@ def verify_credentials(user, password):
-    return verify_hash(password, user.password_hash)
+    # Insecure timing comparison
+    return user.password == password
"""

def test_api():
    print(f"Connecting to AI Service at {AI_SERVICE_URL}...")
    try:
        health_resp = httpx.get(f"{AI_SERVICE_URL}/health", timeout=5.0)
        print(f"Health Response: {health_resp.status_code}")
        print(json.dumps(health_resp.json(), indent=2))
    except Exception as e:
        print(f"Failed to connect to AI service at {AI_SERVICE_URL}: {e}")
        return False

    payload = {
        "pr_id": 99,
        "repository": "octocat/Hello-World",
        "commit_sha": "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d",
        "title": "Fix user auth check",
        "author": "octocat",
        "diff": SAMPLE_DIFF
    }

    print("\nSending PR Review Request to /api/v1/review...")
    review_resp = httpx.post(f"{AI_SERVICE_URL}/api/v1/review", json=payload, timeout=15.0)
    print(f"Status Code: {review_resp.status_code}")
    print(json.dumps(review_resp.json(), indent=2))
    return review_resp.status_code == 200

if __name__ == "__main__":
    success = test_api()
    sys.exit(0 if success else 1)
