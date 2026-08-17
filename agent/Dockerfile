# Build voidswitch-agent in a scratch image from a multi-stage Go build.
FROM golang:1.24-alpine AS build
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download
COPY . .
ARG VERSION=dev
RUN CGO_ENABLED=0 go build -ldflags "-s -w -X main.version=$VERSION" \
    -o /out/voidswitch-agent ./cmd/voidswitch-agent

FROM scratch
COPY --from=build /out/voidswitch-agent /voidswitch-agent
EXPOSE 8443
ENTRYPOINT ["/voidswitch-agent"]
