import mongoose from 'mongoose';

// Disable query buffering so disconnected queries fail fast rather than hanging
mongoose.set('bufferCommands', false);

/**
 * Connect to MongoDB instance using Mongoose.
 * Retries on initial failure to handle container startup lag in Docker Compose.
 */
export async function connectDB(uri) {
  const mongoUri = uri || process.env.MONGODB_URI || 'mongodb://localhost:27017/pr_reviewer_db';
  const maxRetries = 5;
  let attempt = 0;

  while (attempt < maxRetries) {
    try {
      attempt++;
      console.log(`[Database] Attempting connection to MongoDB (attempt ${attempt}/${maxRetries})...`);
      await mongoose.connect(mongoUri, {
        serverSelectionTimeoutMS: 3000,
      });
      console.log(`[Database] Connected successfully to MongoDB at: ${mongoUri.replace(/\/\/.*@/, '//<credentials>@')}`);
      await ensureIndexes();
      return;
    } catch (error) {
      console.warn(`[Database] Connection attempt ${attempt}/${maxRetries} failed: ${error.message}`);
      if (attempt >= maxRetries) {
        console.warn(`[Database] Could not connect to MongoDB after ${maxRetries} attempts. Operating in ephemeral mode.`);
        return;
      }
      await new Promise((res) => setTimeout(res, 1500 * attempt));
    }
  }
}

/**
 * Build every registered model's indexes. With bufferCommands off, Mongoose's automatic index build
 * runs before the connection exists and fails silently, which would leave the unique deliveryId index
 * (the webhook's duplicate guard) missing.
 */
async function ensureIndexes() {
  for (const model of Object.values(mongoose.models)) {
    try {
      await model.createIndexes();
    } catch (error) {
      console.error(`[Database] Could not build indexes for ${model.modelName}: ${error.message}`);
    }
  }
}

export function getDatabaseStatus() {
  const states = ['disconnected', 'connected', 'connecting', 'disconnecting'];
  const stateCode = mongoose.connection.readyState;
  return {
    state: states[stateCode] || 'unknown',
    isConnected: stateCode === 1
  };
}
