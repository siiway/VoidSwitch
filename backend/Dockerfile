# VoidSwitch backend image (Go).
#
# Built from backend/ (the Go module root). Produces a static binary that runs
# against PostgreSQL + Redis. Schema migrations (goose) run at startup.
#
#   docker build -t voidswitch backend/
FROM golang:1.25.1-alpine AS builder
RUN apk add --no-cache ca-certificates git
WORKDIR /src
ENV CGO_ENABLED=0 GOOS=linux
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG VOIDSWITCH_COMMIT=""
ARG VERSION=""
RUN VERSION="${VERSION:-v0.3.0-2026.11.7.1}" && \
    go build -trimpath -ldflags="-s -w" -o /voidswitch ./cmd/voidswitch

FROM alpine:3.21
RUN apk add --no-cache ca-certificates wget && \
    adduser -D -u 10001 voidswitch
WORKDIR /data
COPY --from=builder /voidswitch /usr/local/bin/voidswitch
USER voidswitch
EXPOSE 8080
# Configure via VOIDSWITCH_* env vars (see .env.example).
ENTRYPOINT ["voidswitch"]
