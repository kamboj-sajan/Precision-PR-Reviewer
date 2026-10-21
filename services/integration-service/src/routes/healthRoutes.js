import { Router } from 'express';
import { getDatabaseStatus } from '../config/db.js';
import { checkAiServiceHealth } from '../services/aiServiceClient.js';

const router = Router();

router.get('/health', async (req, res) => {
  const dbStatus = getDatabaseStatus();
  const aiHealth = await checkAiServiceHealth();

  const isHealthy = dbStatus.isConnected || process.env.NODE_ENV === 'test';

  res.status(isHealthy ? 200 : 503).json({
    status: isHealthy ? 'healthy' : 'degraded',
    service: 'integration-service',
    timestamp: new Date().toISOString(),
    uptimeSeconds: process.uptime(),
    dependencies: {
      mongodb: dbStatus,
      aiService: aiHealth,
    },
  });
});

export default router;
