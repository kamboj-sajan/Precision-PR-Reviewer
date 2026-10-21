FROM node:20-alpine

# Set working directory
WORKDIR /app

# Install curl for healthcheck
RUN apk add --no-cache curl

# Install dependencies
COPY package*.json ./
RUN npm install --omit=dev

# Copy application source code
COPY src/ ./src/

# Expose service port
EXPOSE 3000

# Run service
CMD ["node", "src/server.js"]
