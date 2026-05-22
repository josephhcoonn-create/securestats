# syntax=docker/dockerfile:1.7

# ─── Stage 1: build the SPA with Vite ────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Install deps separately so layer caches on package.json / lockfile changes
COPY package.json package-lock.json* ./
RUN npm ci

# Bake the API base URL into the bundle.
# In docker-compose we override to "/api/v1" so the SPA hits its own
# nginx, which proxies through to the backend service.
ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=${VITE_API_URL}

COPY . .
RUN npm run build


# ─── Stage 2: serve with nginx ───────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Drop the default config and ship our SPA + proxy + security headers
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf             /etc/nginx/conf.d/default.conf
COPY security-headers.conf  /etc/nginx/security-headers.conf

# Built static assets
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# Lightweight healthcheck — nginx serves /healthz from its conf
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/healthz >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
