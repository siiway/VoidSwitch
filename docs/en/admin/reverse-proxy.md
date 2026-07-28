# Reverse Proxy

VoidSwitch ships as a two-service stack: the gateway backend (`voidswitch:8080`) and a
front-end nginx (`dashboard`) that serves the SPA and reverse-proxies the API on a
**single origin**. If you need to put another reverse proxy in front of that origin —
for unified TLS termination, path rewriting, or integration into an existing gateway —
the configurations below cover the common setups.

> If you are just running VoidSwitch, `docker compose up -d` is all you need — the
> built-in nginx already handles SPA serving + API reverse proxy. The following is for
> **existing nginx/Caddy instances** where you want to mount VoidSwitch on a sub-path
> or sub-domain.

## API paths

These paths should all point to the backend at `http://backend:8080`:

| Path | Description |
| ---- | ----------- |
| `/v1/` | Core API (`/v1/chat/completions`, `/v1/messages`, `/v1/models`, etc.) |
| `/api/` | Dashboard API (`/api/auth/*`, `/api/me/*`, etc.) |
| `/provider-api/` | Per-provider key management API |
| `/healthz` | Health check endpoint |
| `/install` | Install scripts (`/install.sh`, `/install.ps1`) |
| `/swagger`, `/docs`, `/redoc`, `/openapi.json` | API documentation |

The front-end SPA static files are served separately (see the `root` directive below);
all other paths fall back to `index.html`.

## Nginx

```nginx
# Preserve the client's original protocol when talking to the backend
map $http_x_forwarded_proto $fwd_proto {
    default $scheme;
    "~."    $http_x_forwarded_proto;
}

upstream voidswitch_backend {
    server 127.0.0.1:8080;
}

server {
    listen 80;
    server_name voidswitch.example.com;

    # Chat payloads can be large
    client_max_body_size 25m;

    # ---- API reverse proxy ----
    location ~ ^/(v1|api|provider-api|healthz|install|install\.sh|install\.ps1|swagger|docs|redoc|openapi\.json)(/|$) {
        proxy_pass http://voidswitch_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection "";
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $fwd_proto;
        proxy_set_header X-Forwarded-Host $host;

        # SSE streaming
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # ---- SPA static files ----
    root /path/to/voidswitch-dashboard/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # Long cache for fingerprinted assets
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    location = /index.html {
        add_header Cache-Control "no-cache";
    }
}
```

### SSL / HTTPS

In production, use certbot or acme.sh for automatic certificate management, or add a
`listen 443 ssl` block:

```nginx
server {
    listen 443 ssl;
    server_name voidswitch.example.com;

    ssl_certificate     /etc/letsencrypt/live/voidswitch.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/voidswitch.example.com/privkey.pem;

    # Same location blocks as above…
}

# HTTP → HTTPS redirect
server {
    listen 80;
    server_name voidswitch.example.com;
    return 301 https://$host$request_uri;
}
```

## Caddy

```caddy
voidswitch.example.com {
    # Chat payloads can be large
    request_body {
        max_size 25MB
    }

    # API reverse proxy (all backend paths)
    @api path /v1/* /api/* /provider-api/* /healthz /install /install.sh /install.ps1 /swagger /docs /redoc /openapi.json
    reverse_proxy @api 127.0.0.1:8080 {
        # Forward the client's real IP / protocol
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
        header_up X-Forwarded-Host {host}

        # SSE streaming
        flush_interval -1
    }

    # SPA static files
    root * /path/to/voidswitch-dashboard/dist
    try_files {path} /index.html

    # Long cache for fingerprinted assets
    header /assets/* Cache-Control "public, immutable"
    header /assets/* Expires "+1 year"
    header /index.html Cache-Control "no-cache"

    # Automatic HTTPS
    tls your@email.com
}
```

Caddy automatically obtains and renews Let's Encrypt certificates. The email in `tls`
is used for ACME registration. Omit `tls` or use `tls internal` if you handle TLS
upstream (e.g. behind a CDN).

## Cloudflare Tunnel

If you use `cloudflared` to expose an internal service, simply point the Tunnel at
your nginx/Caddy listener (e.g. `http://localhost:80`). VoidSwitch reads the
`X-Forwarded-Proto` header to determine the client's real protocol, so callback URLs
will correctly use `https://`.
