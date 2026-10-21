import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import { connectDB } from './config/db.js';
import webhookRoutes from './routes/webhookRoutes.js';
import healthRoutes from './routes/healthRoutes.js';

dotenv.config();

const app = express();
const PORT = process.env.PORT || 3000;

// Enable CORS and parse JSON payloads with high limit for large git diffs.
// The raw body is kept so webhook signatures can be verified against the exact bytes GitHub signed.
app.use(cors());
app.use(express.json({
  limit: '25mb',
  verify: (req, res, buf) => {
    req.rawBody = buf;
  },
}));
app.use(express.urlencoded({ extended: true, limit: '25mb' }));

// Request logging middleware
app.use((req, res, next) => {
  console.log(`[HTTP] ${req.method} ${req.url} - ${new Date().toISOString()}`);
  next();
});

// Mount Routes
app.use('/', healthRoutes);
app.use('/api', webhookRoutes);

// Catch-all 404 handler
app.use((req, res) => {
  res.status(404).json({ error: 'Endpoint not found' });
});

// Centralized error handler
app.use((err, req, res, next) => {
  console.error('[ServerError]', err);
  res.status(500).json({
    error: 'Internal Server Error',
    message: err.message,
  });
});

// Bootstrap application & connect to MongoDB
async function startServer() {
  try {
    // Attempt DB connection in non-blocking way so server boots up even if DB starts slowly
    connectDB().catch((err) => {
      console.warn(`[Warning] Initial MongoDB connection postponed: ${err.message}`);
    });

    const server = app.listen(PORT, () => {
      console.log(`=======================================================`);
      console.log(`🚀 Integration Service listening on port ${PORT}`);
      console.log(`📡 GitHub Webhook endpoint: http://localhost:${PORT}/api/webhook`);
      console.log(`❤️  Health check endpoint: http://localhost:${PORT}/health`);
      console.log(`=======================================================`);
    });

    const shutdown = async () => {
      console.log('\n[Process] Gracefully shutting down Integration Service...');
      server.close(() => {
        console.log('[Process] HTTP server closed.');
        process.exit(0);
      });
    };

    process.on('SIGTERM', shutdown);
    process.on('SIGINT', shutdown);
  } catch (error) {
    console.error('[StartupError] Failed to initialize server:', error);
    process.exit(1);
  }
}

startServer();

export default app;
