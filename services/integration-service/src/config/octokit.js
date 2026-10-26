import { Octokit } from '@octokit/rest';

const token = process.env.GITHUB_TOKEN || '';

/** True when a real GitHub token is configured and reviews will be posted to GitHub. */
export const hasLiveGithubToken = Boolean(token) && token !== 'mock_dev_token';

/**
 * Shared Octokit client instance.
 * Auth is optional for public repositories or mocked local pipelines.
 */
export const octokit = new Octokit({
  auth: token && token !== 'mock_dev_token' ? token : undefined,
  userAgent: 'Precision-GitHub-PR-Reviewer-Agent/1.0',
});

/**
 * Fetch raw git diff for a pull request from GitHub API.
 * Uses mediaType 'diff' to stream/return the raw patch format.
 */
export async function fetchPullRequestDiff(owner, repo, pullNumber) {
  try {
    const response = await octokit.rest.pulls.get({
      owner,
      repo,
      pull_number: pullNumber,
      headers: {
        accept: 'application/vnd.github.v3.diff',
      },
    });

    return typeof response.data === 'string' ? response.data : JSON.stringify(response.data);
  } catch (error) {
    console.warn(`[Octokit] Failed to fetch diff via Octokit API for ${owner}/${repo}#${pullNumber}: ${error.message}`);
    return null;
  }
}

/**
 * Hidden HTML comment embedded in every posted review, tying it to the webhook delivery that produced it.
 */
export function reviewMarker(deliveryId) {
  return `<!-- precision-pr-reviewer:delivery=${deliveryId} -->`;
}

/**
 * Whether a review or comment for this delivery is already on the pull request.
 * Lets a retried job (SQS delivers at least once) skip posting the same review twice.
 */
export async function hasPostedReview(owner, repo, pullNumber, deliveryId) {
  if (!hasLiveGithubToken) {
    return false;
  }
  const marker = reviewMarker(deliveryId);
  const [reviews, comments] = await Promise.all([
    octokit.paginate(octokit.rest.pulls.listReviews, { owner, repo, pull_number: pullNumber, per_page: 100 }),
    octokit.paginate(octokit.rest.issues.listComments, { owner, repo, issue_number: pullNumber, per_page: 100 }),
  ]);
  return [...reviews, ...comments].some((item) => (item.body || '').includes(marker));
}

/**
 * Publish a full GitHub Pull Request Review with line-level inline comments
 * using GitHub's native interactive suggestion markdown.
 * Throws if neither the review nor the fallback comment could be posted, so the job is retried.
 */
export async function submitPullRequestReview(owner, repo, pullNumber, commitSha, reviewData, deliveryId) {
  if (!hasLiveGithubToken) {
    console.log(`[Octokit] Skipping live GitHub PR review submission (no active GITHUB_TOKEN configured).`);
    return { mocked: true, message: 'Review generated and stored locally in MongoDB' };
  }

  const marker = deliveryId ? `\n\n${reviewMarker(deliveryId)}` : '';

  try {
    const inlineComments = (reviewData.comments || []).map((c) => {
      let bodyText = `### 🔍 Precision AI Finding: **${c.severity}** [${c.category}]\n\n${c.comment}\n`;
      if (c.suggestedCode) {
        bodyText += `\n\`\`\`suggestion\n${c.suggestedCode}\n\`\`\`\n`;
      }
      return {
        path: c.filePath,
        line: c.lineNumber,
        body: bodyText,
      };
    });

    const reviewEvent = reviewData.verdict === 'REQUEST_CHANGES' ? 'REQUEST_CHANGES' : 'COMMENT';

    const response = await octokit.rest.pulls.createReview({
      owner,
      repo,
      pull_number: pullNumber,
      commit_id: commitSha,
      event: reviewEvent,
      body: `## 🤖 Precision AI Pull Request Review\n\n**Verdict:** ${reviewData.verdict}\n**Confidence Score:** ${(reviewData.confidenceScore * 100).toFixed(1)}%\n\n${reviewData.summary}${marker}`,
      comments: inlineComments.length > 0 ? inlineComments : undefined,
    });

    console.log(`[Octokit] Successfully published review to GitHub PR #${pullNumber} (Review ID: ${response.data.id})`);
    return response.data;
  } catch (error) {
    console.warn(`[Octokit] Failed to post line-level review via GitHub API: ${error.message}. Falling back to issue comment.`);
    // Fallback: post as top-level comment
    try {
      const summaryBody = `### 🤖 Precision AI Review (${reviewData.verdict})\n\n${reviewData.summary}\n\n` +
        (reviewData.comments || []).map(c => `- **${c.filePath}:${c.lineNumber}** [${c.severity}] ${c.comment}`).join('\n') +
        marker;
      const comment = await postReviewComment(owner, repo, pullNumber, summaryBody);
      console.log(`[Octokit] Posted review to GitHub PR #${pullNumber} as an issue comment (Comment ID: ${comment.id})`);
      return comment;
    } catch (fbError) {
      console.error(`[Octokit] Fallback issue comment also failed: ${fbError.message}`);
      throw new Error(`Could not post review to ${owner}/${repo}#${pullNumber}: ${fbError.message}`);
    }
  }
}

/**
 * Fallback helper to post general issue comment onto Pull Request.
 */
export async function postReviewComment(owner, repo, pullNumber, body) {
  if (!hasLiveGithubToken) {
    return { mocked: true, message: 'No GitHub token configured' };
  }

  const response = await octokit.rest.issues.createComment({
    owner,
    repo,
    issue_number: pullNumber,
    body,
  });
  return response.data;
}
