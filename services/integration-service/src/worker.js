import 'dotenv/config';
import { connectDB } from './config/db.js';
import { processReview } from './services/reviewJob.js';
import { usesSqs, runSqsWorker } from './services/reviewQueue.js';

// Review worker: consumes review jobs from SQS. Runs as its own container next to the webhook service.
async function startWorker() {
  if (!usesSqs) {
    // Without SQS the webhook service runs reviews itself; stay up idle so the container isn't restarted in a loop
    console.log('[ReviewWorker] SQS_QUEUE_URL is not set; reviews run inside the webhook service. Idling.');
    setInterval(() => {}, 1 << 30);
    return;
  }

  await connectDB();

  let busy = false;
  let stopping = false;
  const shutdown = () => {
    console.log('[ReviewWorker] Shutting down...');
    stopping = true;
    // Mid-job, let the current review finish; otherwise exit now (an unfinished message is simply retried)
    if (!busy) {
      process.exit(0);
    }
  };
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);

  await runSqsWorker(processReview, {
    shouldStop: () => stopping,
    onBusy: (value) => {
      busy = value;
    },
  });
  process.exit(0);
}

startWorker().catch((error) => {
  console.error('[ReviewWorker] Fatal error:', error);
  process.exit(1);
});
