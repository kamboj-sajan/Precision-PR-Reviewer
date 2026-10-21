import mongoose from 'mongoose';
import { ReviewSession } from '../models/ReviewSession.js';
import { fetchPullRequestDiff, submitPullRequestReview, hasLiveGithubToken } from '../config/octokit.js';
import { forwardDiffToAiService } from '../services/aiServiceClient.js';

/**
 * Main Webhook handler for GitHub Pull Request events.
 * Listens for pull_request actions, extracts the diff, and coordinates RAG review.
 */
export async function handleWebhook(req, res) {
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

  console.log(`[WebhookController] Processing PR #${pullNumber} (${action || 'opened'}) on ${owner}/${repoName}`);

  // 1. Extract git diff
  let diff = payload.diff || payload.gitDiff;
  if (!diff) {
    console.log(`[WebhookController] Fetching diff from GitHub API for ${owner}/${repoName}#${pullNumber}...`);
    diff = await fetchPullRequestDiff(owner, repoName, pullNumber);
  }

  // With a live token, never review a stand-in diff: the review would be posted to a real PR
  if (!diff && hasLiveGithubToken) {
    console.error(`[WebhookController] Could not fetch diff for ${owner}/${repoName}#${pullNumber}; skipping review.`);
    return res.status(502).json({ success: false, error: `Could not fetch diff for ${owner}/${repoName}#${pullNumber}` });
  }

  // If still unavailable (e.g. during local offline testing), use simulated diff
  if (!diff) {
    console.warn(`[WebhookController] No diff from GitHub API. Utilizing sample diff for demonstration.`);
    diff = `--- a/src/auth.js\n+++ b/src/auth.js\n@@ -10,6 +10,8 @@\n function authenticate(user, password) {\n-  return user.password === password;\n+  // Vulnerable to timing attacks\n+  return crypto.timingSafeEqual(Buffer.from(user.password), Buffer.from(password));\n }`;
  }

  // 2. Persist initial review session in MongoDB if connected
  let reviewSession = null;
  if (mongoose.connection.readyState === 1) {
    try {
      reviewSession = new ReviewSession({
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
        diffSnippet: diff.substring(0, 1000),
        diffLength: diff.length,
        status: 'processing',
      });
      await reviewSession.save();
      console.log(`[WebhookController] Created MongoDB ReviewSession: ${reviewSession._id}`);
    } catch (dbError) {
      console.error(`[WebhookController] Error persisting ReviewSession to MongoDB: ${dbError.message}`);
      reviewSession = null;
    }
  } else {
    console.log('[WebhookController] MongoDB not connected; running session in ephemeral mode.');
  }

  try {
    // 3. Dispatch diff and metadata to FastAPI AI / RAG Service
    const aiPayload = {
      pr_id: pullNumber,
      repository: `${owner}/${repoName}`,
      commit_sha: headSha,
      title,
      author: sender,
      diff,
    };

    const aiResponse = await forwardDiffToAiService(aiPayload);
    const reviewData = aiResponse.review || {};

    const formattedReviewResult = {
      summary: reviewData.summary || 'AI Review completed successfully.',
      verdict: reviewData.verdict || 'COMMENT',
      confidenceScore: reviewData.confidence_score || 0.95,
      retrievedContextCount: reviewData.retrieved_context_count || 0,
      comments: (reviewData.comments || []).map((c) => ({
        filePath: c.file_path,
        lineNumber: c.line_number,
        severity: c.severity,
        category: c.category,
        comment: c.comment,
        suggestedCode: c.suggested_code,
        contextSnippet: c.context_snippet,
      })),
    };

    // 4. Update MongoDB ReviewSession with completed AI review
    if (reviewSession && mongoose.connection.readyState === 1) {
      reviewSession.status = 'completed';
      reviewSession.reviewResult = formattedReviewResult;
      await reviewSession.save();
      console.log(`[WebhookController] Updated ReviewSession ${reviewSession._id} to 'completed'.`);
    }

    // 5. Submit PR Review with line comments to GitHub
    await submitPullRequestReview(owner, repoName, pullNumber, headSha, formattedReviewResult);

    return res.status(200).json({
      success: true,
      message: 'PR diff successfully processed and precision review generated.',
      sessionId: reviewSession ? reviewSession._id : 'ephemeral_session',
      review: reviewData,
    });
  } catch (error) {
    console.error(`[WebhookController] Error executing PR review pipeline: ${error.message}`);
    if (reviewSession && mongoose.connection.readyState === 1) {
      reviewSession.status = 'failed';
      reviewSession.errorMessage = error.message;
      await reviewSession.save();
    }
    return res.status(500).json({
      success: false,
      error: error.message,
      sessionId: reviewSession ? reviewSession._id : undefined,
    });
  }
}

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
