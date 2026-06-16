# VoidSwitch dashboard — built with Bun, served by nginx, which also reverse-
# proxies the API to the backend so the whole app lives on one origin.
#
#   docker build -t voidswitch-dashboard ./frontend
#
# VITE_API_BASE is intentionally NOT set: the app falls back to the browser's
# own origin (see src/api/client.ts), so the same image works on any hostname.

# ---- build the static bundle ----
FROM oven/bun:1 AS build
WORKDIR /app

COPY package.json bun.lock ./
RUN bun install
# --frozen-lockfile

COPY . .
RUN bun run build

# ---- serve + proxy ----
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# End-to-end healthcheck: /healthz is proxied through to the backend. Use
# 127.0.0.1, not localhost — nginx listens on IPv4 only, but localhost resolves
# to ::1 first in this image, which would refuse the connection.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/healthz >/dev/null 2>&1 || exit 1
