import crypto from 'node:crypto';

/**
 * Compute the X-Hub-Signature-256 value GitHub sends for a payload.
 */
export function signPayload(secret, rawBody) {
  return 'sha256=' + crypto.createHmac('sha256', secret).update(rawBody).digest('hex');
}

/**
 * Rejects webhook deliveries whose X-Hub-Signature-256 header does not match
 * an HMAC of the raw request body keyed with GITHUB_WEBHOOK_SECRET.
 * Fails closed: if no secret is configured, every delivery is rejected.
 */
export function verifyWebhookSignature(req, res, next) {
  const secret = process.env.GITHUB_WEBHOOK_SECRET;
  if (!secret) {
    console.error('[WebhookSignature] GITHUB_WEBHOOK_SECRET is not set; rejecting webhook delivery.');
    return res.status(500).json({ error: 'Webhook secret not configured' });
  }

  const received = Buffer.from(req.get('x-hub-signature-256') || '');
  const expected = Buffer.from(signPayload(secret, req.rawBody || Buffer.alloc(0)));

  if (received.length !== expected.length || !crypto.timingSafeEqual(received, expected)) {
    console.warn(`[WebhookSignature] Invalid or missing signature on delivery ${req.get('x-github-delivery') || '(no delivery id)'}.`);
    return res.status(401).json({ error: 'Invalid webhook signature' });
  }

  next();
}
