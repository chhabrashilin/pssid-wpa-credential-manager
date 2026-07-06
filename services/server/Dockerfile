# Multi-stage build: compile client + server, then run a slim runtime image.
# Build context is the repo root (see docker-compose.yml).
FROM node:20-alpine AS build
WORKDIR /app

# Install all workspace deps (root + both services).
COPY package.json package-lock.json* ./
COPY services/server/package.json services/server/
COPY services/client/package.json services/client/
RUN npm install

# Build the client, then the server.
COPY . .
RUN npm --workspace services/client run build \
  && npm --workspace services/server run build

# --- Runtime image ---
FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV CLIENT_DIST=/app/client

# Production dependencies only.
COPY package.json package-lock.json* ./
COPY services/server/package.json services/server/
RUN npm install --omit=dev --workspace services/server

# Compiled server + built client assets.
COPY --from=build /app/services/server/dist ./services/server/dist
COPY --from=build /app/services/client/dist ./client

EXPOSE 8080
WORKDIR /app/services/server
CMD ["node", "dist/index.js"]
