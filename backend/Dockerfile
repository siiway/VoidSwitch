# VoidSwitch gateway image (Go).
#
# Built from the REPOSITORY ROOT so the image can bundle both the Go module and
# the OpenCode plugin source that the /install endpoint serves:
#
#   docker build -f backend/Dockerfile -t voidswitch .
#
# (docker compose sets `context: .` + `dockerfile: backend/Dockerfile`.)
FROM golang:1.26-alpine AS builder
RUN apk add --no-cache ca-certificates git
WORKDIR /src/backend
ENV CGO_ENABLED=0 GOOS=linux
COPY backend/go.mod backend/go.sum ./
RUN go mod download
COPY backend/ ./
ARG VOIDSWITCH_COMMIT=""
ARG VERSION=""
RUN VERSION="${VERSION:-0.3.0-2026.11.8.11}" && \
    go build -trimpath -ldflags="-s -w" -o /voidswitch ./cmd/voidswitch

FROM alpine:3.21
RUN apk add --no-cache ca-certificates wget && \
    adduser -D -u 10001 voidswitch
WORKDIR /app
COPY --from=builder /voidswitch /usr/local/bin/voidswitch
# OpenCode plugin sources, served by GET /opencode/voidswitch.ts (V2) and
# /opencode/voidswitch-v1.ts (V1), plus the /install scripts. The handlers walk
# up from the working dir looking for opencode-plugin{,-v1}/src/index.ts, so
# placing both trees beside /app is enough.
COPY opencode-plugin/src /app/opencode-plugin/src
COPY opencode-plugin-v1/src /app/opencode-plugin-v1/src
USER voidswitch
EXPOSE 8080
# Configure via VOIDSWITCH_* env vars (see .env.example).
ENTRYPOINT ["voidswitch"]
