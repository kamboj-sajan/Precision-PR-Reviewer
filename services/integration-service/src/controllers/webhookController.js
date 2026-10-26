import crypto from 'node:crypto';
import mongoose from 'mongoose';
import { ReviewSession } from '../models/ReviewSession.js';
import { enqueueReview } from '../services/reviewQueue.js';

const defaultDeps = {
  isDatabaseReady: () => mongoose.connection.readyState === 1,
  createSession: (doc) => ReviewSession.create(doc),
  deleteSession: (id) => ReviewSession.deleteOne({ _id: id }),
  enqueueReview,
};

/**
 * Build the GitHub webhook handler. It only records and queues the delivery, then answers 202 right away:
 * GitHub gives up on a delivery after 10 seconds, and a review can take longer than that.
 * The review itself runs in the worker (see services/reviewJob.js).
 */
export function createWebhookHandler(deps = defaultDeps) {
  return async function handleWebhook(req, res) {
    const githubEvent = req.headers['x-github-event'] || 'pull_request';

    // Handle GitHub ping events for initial webhook handshake
    if (githubEvent === 'ping') {
      console.log('[WebhookController] Received GitHub ping event. Responding with pong.');
      return res.status(200).json({ msg: 'pong', zen: req.body?.zen });
    }

    if (githubEvent !== 'pull_request') {
      console.log(`[WebhookController] Ignoring unhandled event: ${githubEvent}`);
      return res.status(200).json({ message: `Ignored event: ${githubEvent}` });
    }

    const payload = req.body;
    const action = payload.action;

    // Process PR lifecycle events: opened, synchronize (new commits pushed), reopened
    const validActions = ['opened', 'synchronize', 'reopened'];
    if (action && !validActions.includes(action)) {
      console.log(`[WebhookController] Pull Request action '${action}' ignored.`);
      return res.status(200).json({ message: `Action '${action}' ignored` });
    }

    // Extract PR context from webhook payload
    const pr = payload.pull_request || payload;
    const repository = payload.repository || {
      owner: { login: req.body.owner || 'unknown' },
      name: req.body.repo || 'unknown-repo',
      full_name: `${req.body.owner || 'unknown'}/${req.body.repo || 'unknown-repo'}`
    };

    const owner = repository.owner?.login || repository.owner?.name || 'unknown-owner';
    const repoName = repository.name || 'unknown-repo';
    const pullNumber = pr.number || payload.number || 1;
    const headSha = pr.head?.sha || payload.headSha || 'HEAD';
    const headRef = pr.head?.ref || 'feature-branch';
    const baseRef = pr.base?.ref || 'main';
    const title = pr.title || 'PR Review Request';
    const sender = payload.sender?.login || 'github-user';

    // The delivery record is what makes redeliveries safe, so without the database the delivery is refused
    if (!deps.isDatabaseReady()) {
      console.error('[WebhookController] MongoDB not connected; rejecting delivery so it can be redelivered.');
      return res.status(503).json({ success: false, error: 'Database unavailable; redeliver later' });
    }

    const deliveryId = req.get('x-github-delivery') || `local-${crypto.randomUUID()}`;

    let session;
    try {
      session = await deps.createSession({
        deliveryId,
        repository: {
          owner,
          name: repoName,
          fullName: repository.full_name || `${owner}/${repoName}`,
        },
        pullNumber,
        title,
        action: action || 'opened',
        sender,
        baseRef,
        headRef,
        headSha,
        inlineDiff: payload.diff || payload.gitDiff,
        status: 'queued',
      });
    } catch (error) {
      if (error.code === 11000) {
        console.log(`[WebhookController] Delivery ${deliveryId} was already received; ignoring the duplicate.`);
        return res.status(200).json({ success: true, duplicate: true, deliveryId });
      }
      console.error(`[WebhookController] Could not record delivery ${deliveryId}: ${error.message}`);
      return res.status(500).json({ success: false, error: 'Could not record delivery' });
    }

    try {
      await deps.enqueueReview({ deliveryId });
    } catch (error) {
      // Forget the delivery so GitHub's redelivery is accepted instead of being treated as a duplicate
      await deps.deleteSession(session._id).catch(() => {});
      console.error(`[WebhookController] Could not queue review for delivery ${deliveryId}: ${error.message}`);
      return res.status(503).json({ success: false, error: 'Could not queue review; redeliver later' });
    }

    console.log(`[WebhookController] Queued review for PR #${pullNumber} (${action || 'opened'}) on ${owner}/${repoName} (delivery ${deliveryId}).`);
    return res.status(202).json({
      success: true,
      queued: true,
      deliveryId,
      sessionId: session._id,
    });
  };
}

export const handleWebhook = createWebhookHandler();

/**
 * Retrieve review history by PR or list all sessions.
 */
export async function listReviews(req, res) {
  try {
    if (mongoose.connection.readyState !== 1) {
      return res.status(200).json({ success: true, count: 0, reviews: [], note: 'MongoDB offline; in-memory/ephemeral mode' });
    }
    const reviews = await ReviewSession.find().sort({ createdAt: -1 }).limit(20);
    res.status(200).json({ success: true, count: reviews.length, reviews });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
}

/**
 * Retrieve a specific review session by ID.
 */
export async function getReview(req, res) {
  try {
    if (mongoose.connection.readyState !== 1) {
      return res.status(404).json({ success: false, error: 'MongoDB offline' });
    }
    const review = await ReviewSession.findById(req.params.id);
    if (!review) {
      return res.status(404).json({ success: false, error: 'Review not found' });
    }
    res.status(200).json({ success: true, review });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
}
