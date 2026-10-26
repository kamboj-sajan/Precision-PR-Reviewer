import { ReviewSession } from '../models/ReviewSession.js';
import {
  fetchPullRequestDiff,
  submitPullRequestReview,
  hasPostedReview,
  hasLiveGithubToken,
} from '../config/octokit.js';
import { forwardDiffToAiService } from './aiServiceClient.js';

// Stand-in diff for offline demos only; never used when a real GitHub token is configured
const SAMPLE_DIFF = `--- a/src/auth.js\n+++ b/src/auth.js\n@@ -10,6 +10,8 @@\n function authenticate(user, password) {\n-  return user.password === password;\n+  // Vulnerable to timing attacks\n+  return crypto.timingSafeEqual(Buffer.from(user.password), Buffer.from(password));\n }`;

const defaultDeps = {
  findSession: (deliveryId) => ReviewSession.findOne({ deliveryId }),
  fetchPullRequestDiff,
  forwardDiffToAiService,
  hasPostedReview,
  submitPullRequestReview,
  hasLiveGithubToken,
};

function formatReview(reviewData) {
  return {
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
}

/**
 * Run one queued review: fetch the diff, call the AI/RAG service, post the review to GitHub.
 * Safe to run more than once for the same delivery (queues deliver at least once): a completed
 * session, or a PR that already carries this delivery's review marker, is never posted to again.
 * Throws when the job should be retried; on the final attempt the session is marked failed first.
 */
export async function processReview(deliveryId, { attempt = 1, finalAttempt = true } = {}, deps = defaultDeps) {
  const session = await deps.findSession(deliveryId);
  if (!session) {
    // Unprocessable, so let it exhaust its retries and land in the dead-letter queue for inspection
    throw new Error(`No review session found for delivery ${deliveryId}`);
  }
  if (session.status === 'completed') {
    console.log(`[ReviewJob] Delivery ${deliveryId} already completed; skipping.`);
    return session;
  }

  const { owner, name: repo, fullName } = session.repository;
  const pullNumber = session.pullNumber;
  session.status = 'processing';
  session.attempts = attempt;
  await session.save();

  try {
    if (await deps.hasPostedReview(owner, repo, pullNumber, deliveryId)) {
      console.log(`[ReviewJob] Review for delivery ${deliveryId} is already on ${fullName}#${pullNumber}; skipping.`);
      session.status = 'completed';
      await session.save();
      return session;
    }

    let diff = session.inlineDiff || (await deps.fetchPullRequestDiff(owner, repo, pullNumber));
    if (diff === null) {
      if (deps.hasLiveGithubToken) {
        throw new Error(`Could not fetch diff for ${fullName}#${pullNumber}`);
      }
      console.warn(`[ReviewJob] No diff from GitHub API. Utilizing sample diff for demonstration.`);
      diff = SAMPLE_DIFF;
    }
    if (!diff.trim()) {
      console.log(`[ReviewJob] ${fullName}#${pullNumber} has no changes; nothing to review.`);
      session.status = 'completed';
      session.errorMessage = 'Empty diff; nothing to review';
      await session.save();
      return session;
    }
    session.diffSnippet = diff.substring(0, 1000);
    session.diffLength = diff.length;

    const aiResponse = await deps.forwardDiffToAiService({
      pr_id: pullNumber,
      repository: fullName,
      commit_sha: session.headSha,
      title: session.title,
      author: session.sender,
      diff,
    });
    session.reviewResult = formatReview(aiResponse.review || {});

    await deps.submitPullRequestReview(owner, repo, pullNumber, session.headSha, session.reviewResult, deliveryId);

    session.status = 'completed';
    session.errorMessage = undefined;
    await session.save();
    console.log(`[ReviewJob] Completed review for ${fullName}#${pullNumber} (delivery ${deliveryId}, attempt ${attempt}).`);
    return session;
  } catch (error) {
    session.status = finalAttempt ? 'failed' : 'queued';
    session.errorMessage = error.message;
    await session.save();
    throw error;
  }
}
