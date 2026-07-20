# ─────────────────────────────────────────────────────────────────────────────
# Frontend Dev Server — Vite on Node 20 Alpine
# ─────────────────────────────────────────────────────────────────────────────
FROM node:20-alpine

WORKDIR /app

# Install deps first (layer-cached unless package.json changes)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source
COPY . .

EXPOSE 5173

# --host exposes Vite outside the container so Docker port-mapping works
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
