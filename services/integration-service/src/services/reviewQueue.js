import {
  SQSClient,
  SendMessageCommand,
  ReceiveMessageCommand,
  DeleteMessageCommand,
  ChangeMessageVisibilityCommand,
} from '@aws-sdk/client-sqs';

const queueUrl = process.env.SQS_QUEUE_URL || '';
// Must match maxReceiveCount in the queue's redrive policy: the receive that reaches it is the last attempt
export const maxReceives = Number(process.env.SQS_MAX_RECEIVES || 3);
export const usesSqs = Boolean(queueUrl);

let client = null;
function sqs() {
  if (!client) {
    client = new SQSClient({ region: process.env.AWS_REGION || 'ap-southeast-2' });
  }
  return client;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Hand a review job to the worker. With SQS configured the job is durable: SQS retries it and moves it
 * to the dead-letter queue after maxReceives. Without SQS (local development), the job runs in this
 * process in the background with the same retry budget.
 */
export async function enqueueReview(job) {
  if (usesSqs) {
    await sqs().send(new SendMessageCommand({ QueueUrl: queueUrl, MessageBody: JSON.stringify(job) }));
    return;
  }
  const { processReview } = await import('./reviewJob.js');
  runInProcess(job, processReview).catch((error) => console.error(`[ReviewQueue] ${error.message}`));
}

/**
 * In-process fallback: up to maxReceives attempts with a growing delay. Resolves to whether it succeeded.
 */
export async function runInProcess(job, handler, { delayMs = 5000 } = {}) {
  for (let attempt = 1; attempt <= maxReceives; attempt++) {
    try {
      await handler(job.deliveryId, { attempt, finalAttempt: attempt === maxReceives });
      return true;
    } catch (error) {
      console.error(`[ReviewQueue] Job ${job.deliveryId} failed on attempt ${attempt}/${maxReceives}: ${error.message}`);
      if (attempt < maxReceives) {
        await sleep(delayMs * attempt);
      }
    }
  }
  return false;
}

/**
 * Process one SQS message. It is deleted only after the review succeeds; on failure it becomes visible
 * again after a short backoff (instead of the queue's 10-minute visibility timeout), and SQS moves it to
 * the dead-letter queue once it has been received maxReceives times.
 */
export async function handleMessage(message, handler, { client: sqsClient = sqs(), url = queueUrl, backoffSeconds = 30 } = {}) {
  const attempt = Number(message.Attributes?.ApproximateReceiveCount || 1);
  let deliveryId = null;
  try {
    deliveryId = JSON.parse(message.Body).deliveryId;
  } catch {
    // Malformed body; handled below like any other failure so it ends up in the dead-letter queue
  }

  try {
    if (!deliveryId) {
      throw new Error(`Malformed job message ${message.MessageId}`);
    }
    await handler(deliveryId, { attempt, finalAttempt: attempt >= maxReceives });
    await sqsClient.send(new DeleteMessageCommand({ QueueUrl: url, ReceiptHandle: message.ReceiptHandle }));
    return 'done';
  } catch (error) {
    console.error(`[ReviewWorker] Job ${deliveryId || message.MessageId} failed on attempt ${attempt}/${maxReceives}: ${error.message}`);
    await sqsClient
      .send(new ChangeMessageVisibilityCommand({
        QueueUrl: url,
        ReceiptHandle: message.ReceiptHandle,
        VisibilityTimeout: backoffSeconds * attempt,
      }))
      .catch((visibilityError) => console.error(`[ReviewWorker] Could not shorten retry delay: ${visibilityError.message}`));
    return 'retry';
  }
}

/**
 * Long-poll SQS until shouldStop() returns true, handling one message at a time.
 * onBusy(true/false) brackets each job so the process can shut down cleanly between jobs.
 */
export async function runSqsWorker(handler, { shouldStop = () => false, onBusy = () => {} } = {}) {
  console.log(`[ReviewWorker] Polling ${queueUrl} (dead-letter after ${maxReceives} attempts).`);
  while (!shouldStop()) {
    let messages = [];
    try {
      const response = await sqs().send(new ReceiveMessageCommand({
        QueueUrl: queueUrl,
        MaxNumberOfMessages: 1,
        WaitTimeSeconds: 20,
        MessageSystemAttributeNames: ['ApproximateReceiveCount'],
      }));
      messages = response.Messages || [];
    } catch (error) {
      console.error(`[ReviewWorker] Could not receive from SQS: ${error.message}`);
      await sleep(5000);
      continue;
    }

    for (const message of messages) {
      onBusy(true);
      try {
        await handleMessage(message, handler);
      } finally {
        onBusy(false);
      }
    }
  }
}
