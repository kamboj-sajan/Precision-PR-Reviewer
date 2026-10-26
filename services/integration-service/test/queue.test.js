import test from 'node:test';
import assert from 'node:assert';
import { createWebhookHandler } from '../src/controllers/webhookController.js';
import { processReview } from '../src/services/reviewJob.js';
import { handleMessage, runInProcess, maxReceives } from '../src/services/reviewQueue.js';

function fakeRes() {
  const res = { statusCode: 200, body: null };
  res.status = (code) => { res.statusCode = code; return res; };
  res.json = (body) => { res.body = body; return res; };
  return res;
}

function prRequest(deliveryId) {
  const headers = { 'x-github-event': 'pull_request', 'x-github-delivery': deliveryId };
  return {
    headers,
    get: (name) => headers[name.toLowerCase()],
    body: {
      action: 'opened',
      repository: { name: 'app', full_name: 'acme/app', owner: { login: 'acme' } },
      pull_request: { number: 7, title: 'Add login', head: { sha: 'abc', ref: 'feat' }, base: { ref: 'main' } },
    },
  };
}

function webhookDeps(overrides = {}) {
  const calls = { created: [], enqueued: [], deleted: [] };
  const seen = new Set();
  const deps = {
    isDatabaseReady: () => true,
    createSession: async (doc) => {
      if (seen.has(doc.deliveryId)) {
        throw Object.assign(new Error('E11000 duplicate key'), { code: 11000 });
      }
      seen.add(doc.deliveryId);
      calls.created.push(doc);
      return { _id: `session-${doc.deliveryId}` };
    },
    deleteSession: async (id) => { calls.deleted.push(id); },
    enqueueReview: async (job) => { calls.enqueued.push(job); },
    ...overrides,
  };
  return { deps, calls };
}

test('Webhook queues a new delivery and answers 202 without waiting for the review', async () => {
  const { deps, calls } = webhookDeps();
  const res = fakeRes();
  await createWebhookHandler(deps)(prRequest('d-1'), res);
  assert.strictEqual(res.statusCode, 202);
  assert.deepStrictEqual(calls.enqueued, [{ deliveryId: 'd-1' }]);
  assert.strictEqual(calls.created[0].status, 'queued');
});

test('Webhook ignores a redelivery of the same delivery ID', async () => {
  const { deps, calls } = webhookDeps();
  const handler = createWebhookHandler(deps);
  await handler(prRequest('d-1'), fakeRes());
  const res = fakeRes();
  await handler(prRequest('d-1'), res);
  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(res.body.duplicate, true);
  assert.strictEqual(calls.enqueued.length, 1);
});

test('Webhook forgets the delivery when it cannot be queued, so GitHub can redeliver it', async () => {
  const { deps, calls } = webhookDeps({ enqueueReview: async () => { throw new Error('SQS unavailable'); } });
  const res = fakeRes();
  await createWebhookHandler(deps)(prRequest('d-2'), res);
  assert.strictEqual(res.statusCode, 503);
  assert.deepStrictEqual(calls.deleted, ['session-d-2']);
});

test('Webhook refuses deliveries while the database is down', async () => {
  const { deps, calls } = webhookDeps({ isDatabaseReady: () => false });
  const res = fakeRes();
  await createWebhookHandler(deps)(prRequest('d-3'), res);
  assert.strictEqual(res.statusCode, 503);
  assert.strictEqual(calls.enqueued.length, 0);
});

function fakeSession(overrides = {}) {
  return {
    repository: { owner: 'acme', name: 'app', fullName: 'acme/app' },
    pullNumber: 7,
    headSha: 'abc',
    title: 'Add login',
    sender: 'dev',
    status: 'queued',
    saves: 0,
    async save() { this.saves++; },
    ...overrides,
  };
}

function jobDeps(session, overrides = {}) {
  const calls = { ai: 0, posted: [] };
  const deps = {
    findSession: async () => session,
    fetchPullRequestDiff: async () => '--- a/x.js\n+++ b/x.js\n@@ -1 +1 @@\n-a\n+b\n',
    forwardDiffToAiService: async () => { calls.ai++; return { review: { summary: 'ok', verdict: 'COMMENT', comments: [] } }; },
    hasPostedReview: async () => false,
    submitPullRequestReview: async (...args) => { calls.posted.push(args); },
    hasLiveGithubToken: true,
    ...overrides,
  };
  return { deps, calls };
}

test('Review job posts the review tagged with its delivery ID and completes the session', async () => {
  const session = fakeSession();
  const { deps, calls } = jobDeps(session);
  await processReview('d-1', { attempt: 1, finalAttempt: false }, deps);
  assert.strictEqual(session.status, 'completed');
  assert.strictEqual(calls.posted.length, 1);
  assert.strictEqual(calls.posted[0][5], 'd-1');
});

test('Review job never posts twice: completed sessions and already-posted reviews are skipped', async () => {
  const done = fakeSession({ status: 'completed' });
  const first = jobDeps(done);
  await processReview('d-1', {}, first.deps);
  assert.strictEqual(first.calls.ai, 0);
  assert.strictEqual(first.calls.posted.length, 0);

  // Crashed after posting but before marking the session completed
  const crashed = fakeSession({ status: 'processing' });
  const second = jobDeps(crashed, { hasPostedReview: async () => true });
  await processReview('d-1', {}, second.deps);
  assert.strictEqual(crashed.status, 'completed');
  assert.strictEqual(second.calls.ai, 0);
  assert.strictEqual(second.calls.posted.length, 0);
});

test('Review job completes empty pull requests without calling the AI service', async () => {
  const session = fakeSession();
  const { deps, calls } = jobDeps(session, { fetchPullRequestDiff: async () => '' });
  await processReview('d-1', {}, deps);
  assert.strictEqual(session.status, 'completed');
  assert.strictEqual(calls.ai, 0);
});

test('Review job failures stay queued for retry, and are marked failed on the final attempt', async () => {
  const unreachable = { fetchPullRequestDiff: async () => null };
  const retrying = fakeSession();
  await assert.rejects(processReview('d-1', { attempt: 1, finalAttempt: false }, jobDeps(retrying, unreachable).deps));
  assert.strictEqual(retrying.status, 'queued');

  const last = fakeSession();
  await assert.rejects(processReview('d-1', { attempt: 3, finalAttempt: true }, jobDeps(last, unreachable).deps));
  assert.strictEqual(last.status, 'failed');
  assert.match(last.errorMessage, /Could not fetch diff/);
});

function fakeSqs() {
  const sent = [];
  return { sent, send: async (command) => { sent.push(command); return {}; } };
}

const message = (body, receiveCount) => ({
  MessageId: 'm-1',
  ReceiptHandle: 'rh-1',
  Body: body,
  Attributes: { ApproximateReceiveCount: String(receiveCount) },
});

test('SQS worker deletes a message only after the review succeeds', async () => {
  const sqs = fakeSqs();
  const outcome = await handleMessage(message('{"deliveryId":"d-1"}', 1), async () => {}, { client: sqs, url: 'q' });
  assert.strictEqual(outcome, 'done');
  assert.deepStrictEqual(sqs.sent.map((c) => c.constructor.name), ['DeleteMessageCommand']);
});

test('SQS worker leaves failed messages for retry with a growing delay, flagging the final attempt', async () => {
  const sqs = fakeSqs();
  const flags = [];
  const failing = async (id, { finalAttempt }) => { flags.push(finalAttempt); throw new Error('boom'); };

  await handleMessage(message('{"deliveryId":"d-1"}', 2), failing, { client: sqs, url: 'q', backoffSeconds: 30 });
  await handleMessage(message('{"deliveryId":"d-1"}', maxReceives), failing, { client: sqs, url: 'q', backoffSeconds: 30 });

  assert.deepStrictEqual(sqs.sent.map((c) => c.constructor.name), ['ChangeMessageVisibilityCommand', 'ChangeMessageVisibilityCommand']);
  assert.strictEqual(sqs.sent[0].input.VisibilityTimeout, 60);
  assert.deepStrictEqual(flags, [false, true]);
});

test('SQS worker treats malformed messages as failures so they reach the dead-letter queue', async () => {
  const sqs = fakeSqs();
  let called = false;
  const outcome = await handleMessage(message('not json', 1), async () => { called = true; }, { client: sqs, url: 'q' });
  assert.strictEqual(outcome, 'retry');
  assert.strictEqual(called, false);
});

test('In-process fallback retries up to the same budget as SQS', async () => {
  let attempts = 0;
  const ok = await runInProcess({ deliveryId: 'd-1' }, async () => { attempts++; throw new Error('boom'); }, { delayMs: 0 });
  assert.strictEqual(ok, false);
  assert.strictEqual(attempts, maxReceives);
});
