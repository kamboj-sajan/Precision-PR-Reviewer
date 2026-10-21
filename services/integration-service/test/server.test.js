import test from 'node:test';
import assert from 'node:assert';
import { getDatabaseStatus } from '../src/config/db.js';
import { octokit } from '../src/config/octokit.js';
import { signPayload, verifyWebhookSignature } from '../src/middleware/verifyWebhookSignature.js';

test('Database status helper returns expected shape', () => {
  const status = getDatabaseStatus();
  assert.ok(status);
  assert.strictEqual(typeof status.isConnected, 'boolean');
  assert.strictEqual(typeof status.state, 'string');
});

test('Octokit instance initializes correctly', () => {
  assert.ok(octokit);
  assert.ok(octokit.rest);
  assert.ok(octokit.rest.pulls);
  assert.ok(octokit.rest.issues);
});

function runSignatureCheck({ secret, body, signature }) {
  process.env.GITHUB_WEBHOOK_SECRET = secret;
  const headers = { 'x-hub-signature-256': signature };
  const req = { rawBody: Buffer.from(body), get: (name) => headers[name.toLowerCase()] };
  const result = { status: 200, nextCalled: false };
  const res = {
    status(code) { result.status = code; return this; },
    json() { return this; },
  };
  verifyWebhookSignature(req, res, () => { result.nextCalled = true; });
  return result;
}

test('Webhook signature check accepts a correctly signed payload', () => {
  const body = '{"action":"opened"}';
  const result = runSignatureCheck({ secret: 's3cret', body, signature: signPayload('s3cret', body) });
  assert.strictEqual(result.nextCalled, true);
});

test('Webhook signature check rejects wrong, missing, and tampered signatures', () => {
  const body = '{"action":"opened"}';
  assert.strictEqual(runSignatureCheck({ secret: 's3cret', body, signature: signPayload('other', body) }).status, 401);
  assert.strictEqual(runSignatureCheck({ secret: 's3cret', body, signature: undefined }).status, 401);
  assert.strictEqual(runSignatureCheck({ secret: 's3cret', body: body + ' ', signature: signPayload('s3cret', body) }).status, 401);
});

test('Webhook signature check fails closed when no secret is configured', () => {
  const body = '{"action":"opened"}';
  const result = runSignatureCheck({ secret: '', body, signature: signPayload('anything', body) });
  assert.strictEqual(result.status, 500);
  assert.strictEqual(result.nextCalled, false);
});
