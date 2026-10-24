# ==============================================================================
# Tenant Dashboard - Production Multi-Stage Dockerfile
# Build Context: Repository Root (.)
# ==============================================================================

# Stage 1: Build static assets
FROM node:20-alpine AS builder

WORKDIR /app

# Copy dependency manifests first for build caching
COPY apps/tenant-dashboard/package.json apps/tenant-dashboard/package-lock.json ./

# Install dependencies deterministically via lockfile
RUN npm ci

# Copy dashboard source code and configuration
COPY apps/tenant-dashboard/ ./

# Compile TypeScript and build production bundle
RUN npm run build

# Stage 2: Serve with Nginx Alpine
FROM nginx:alpine

# Remove default Nginx static files
RUN rm -rf /usr/share/nginx/html/*

# Copy custom Nginx configuration
COPY apps/tenant-dashboard/nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled static assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# Container healthcheck
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
