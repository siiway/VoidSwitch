FROM golang:1.25-alpine AS builder
RUN apk add --no-cache gcc musl-dev
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=1 go build -ldflags="-s -w" -o /voidswitch ./cmd/voidswitch

FROM alpine:3.21
RUN apk add --no-cache ca-certificates wget
COPY --from=builder /voidswitch /usr/local/bin/voidswitch
WORKDIR /data
EXPOSE 8080
ENTRYPOINT ["voidswitch"]
