import { Router } from 'express';
import { handleWebhook, listReviews, getReview } from '../controllers/webhookController.js';
import { verifyWebhookSignature } from '../middleware/verifyWebhookSignature.js';

const router = Router();

// Primary GitHub Webhook receiver (only accepts deliveries signed with GITHUB_WEBHOOK_SECRET)
router.post('/webhook', verifyWebhookSignature, handleWebhook);

// PR Review query endpoints
router.get('/reviews', listReviews);
router.get('/reviews/:id', getReview);

export default router;
