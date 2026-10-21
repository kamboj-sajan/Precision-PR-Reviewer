import axios from 'axios';

const aiServiceUrl = process.env.AI_SERVICE_URL || 'http://localhost:8000';

/**
 * Client to communicate with the FastAPI AI / RAG Service.
 * Transmits the git diff and PR metadata for precision retrieval and review generation.
 */
export async function forwardDiffToAiService(payload) {
  const url = `${aiServiceUrl}/api/v1/review`;
  console.log(`[AIServiceClient] Forwarding PR diff to RAG service at: ${url}`);

  try {
    const response = await axios.post(url, payload, {
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 300000, // 5 min timeout for RAG retrieval + LLM inference on large diffs
    });

    console.log(`[AIServiceClient] Received review from AI service with ${response.data?.review?.comments?.length || 0} comments.`);
    return response.data;
  } catch (error) {
    if (error.response) {
      console.error(`[AIServiceClient] AI service responded with error status ${error.response.status}:`, error.response.data);
      throw new Error(`AI Service Error (${error.response.status}): ${JSON.stringify(error.response.data)}`);
    } else if (error.request) {
      console.error(`[AIServiceClient] No response received from AI service at ${url}: ${error.message}`);
      throw new Error(`AI Service unreachable at ${url}: ${error.message}`);
    } else {
      console.error(`[AIServiceClient] Error configuring request to AI service: ${error.message}`);
      throw error;
    }
  }
}

/**
 * Health probe for AI Service connectivity.
 */
export async function checkAiServiceHealth() {
  try {
    const response = await axios.get(`${aiServiceUrl}/health`, { timeout: 3000 });
    return { status: 'connected', data: response.data };
  } catch (error) {
    return { status: 'unreachable', error: error.message };
  }
}
