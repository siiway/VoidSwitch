# DEPRECATED — the gateway image is now the Go backend.
#
# Build it from the repository root with the backend Dockerfile:
#
#   docker build -f backend/Dockerfile -t voidswitch .
#
# (docker compose does this automatically; see compose-build.override.yaml.)
#
# The Python gateway's image lives on the `legacy` branch. This placeholder is
# kept only so old commands that reference `-f Dockerfile` fail with a clear
# message rather than silently building the wrong thing.

FROM alpine:3.21
RUN echo "VoidSwitch now builds from backend/Dockerfile (Go). See docs/migration/." >&2 && exit 1
