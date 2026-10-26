#!/usr/bin/env bash
# ========================================================
# Simulate GitHub Pull Request Webhook Event
# ========================================================

TARGET_URL="${1:-http://localhost:3000/api/webhook}"
# Must match GITHUB_WEBHOOK_SECRET on the integration service, or the delivery is rejected with 401
# Set DELIVERY_ID to resend the same delivery and see the duplicate guard ignore it
WEBHOOK_SECRET="${GITHUB_WEBHOOK_SECRET:-development_secret_token}"

echo "📡 Simulating GitHub Pull Request Webhook Event to: ${TARGET_URL}"

SAMPLE_PAYLOAD=$(cat << 'JSON'
{
  "action": "opened",
  "number": 42,
  "repository": {
    "name": "ecommerce-backend",
    "full_name": "acme-corp/ecommerce-backend",
    "owner": {
      "login": "acme-corp"
    }
  },
  "pull_request": {
    "number": 42,
    "title": "feat: Add user authentication and password verification",
    "user": {
      "login": "developer-alice"
    },
    "head": {
      "sha": "a1b2c3d4e5f67890123456789abcdef012345678",
      "ref": "feat/user-auth"
    },
    "base": {
      "ref": "main"
    }
  },
  "diff": "--- a/src/services/authService.js\n+++ b/src/services/authService.js\n@@ -25,7 +25,8 @@ class AuthService {\n   async verifyPassword(storedPassword, inputPassword) {\n     // Compare incoming password with hash\n-    return bcrypt.compare(inputPassword, storedPassword);\n+    // Quick equality check (VULNERABLE: Timing attack)\n+    return storedPassword === inputPassword;\n   }\n }\n--- a/src/controllers/userController.js\n+++ b/src/controllers/userController.js\n@@ -40,6 +40,7 @@ export async function getUser(req, res) {\n   console.log('Fetching user ID:', req.params.id);\n+  const query = 'SELECT * FROM users WHERE id = ' + req.params.id;\n   return res.json({ status: 'ok' });\n }"
}
JSON
)

# Sign the exact payload bytes the same way GitHub does (HMAC-SHA256 -> X-Hub-Signature-256)
SIGNATURE="sha256=$(printf '%s' "${SAMPLE_PAYLOAD}" | openssl dgst -sha256 -hmac "${WEBHOOK_SECRET}" | sed 's/^.* //')"

curl -X POST "${TARGET_URL}" \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: pull_request" \
  -H "X-Hub-Signature-256: ${SIGNATURE}" \
  -H "X-GitHub-Delivery: ${DELIVERY_ID:-$(uuidgen | tr '[:upper:]' '[:lower:]')}" \
  --data-binary "${SAMPLE_PAYLOAD}"

echo -e "\n\n✅ Webhook simulation complete."
