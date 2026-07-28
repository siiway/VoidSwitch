# 反向代理

VoidSwitch 整体部署后，网关后端（`voidswitch:8080`）和前端的 nginx（`dashboard`）一道
通过一个**单一源站**对外提供服务。如果你需要在这个源站前面再加一层反向代理——
例如统一 SSL 终结、路径重写、接入已有网关——可以参考下面的配置。

> 如果你只是想跑 VoidSwitch，直接用 `docker compose up -d` 即可，内置的 nginx 已经
> 做好了 SPA 托管 + API 反代。以下配置适用于**已有 nginx/Caddy 实例**，希望把 VoidSwitch
> 挂载到某个子路径或子域名的场景。

## API 路径

需要反代的路径（全部指向后端 `http://backend:8080`）：

| 路径 | 说明 |
| ---- | ---- |
| `/v1/` | 核心 API（`/v1/chat/completions`、`/v1/messages`、`/v1/models` 等） |
| `/api/` | 控制台 API（`/api/auth/*`、`/api/me/*` 等） |
| `/provider-api/` | 供应商密钥管理 API |
| `/healthz` | 健康检查 |
| `/install` | 安装脚本（`/install.sh`、`/install.ps1`） |
| `/swagger`、`/docs`、`/redoc`、`/openapi.json` | API 文档 |

前端 SPA 的静态文件单独托管（见下面配置中的 `root` 指向），其余路径 fallback 到
`index.html`。

## Nginx

```nginx
# 与后端通信时保留客户端真实协议
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

    # 聊天请求体较大
    client_max_body_size 25m;

    # ---- API 反代 ----
    location ~ ^/(v1|api|provider-api|healthz|install|install\.sh|install\.ps1|swagger|docs|redoc|openapi\.json)(/|$) {
        proxy_pass http://voidswitch_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection "";
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $fwd_proto;
        proxy_set_header X-Forwarded-Host $host;

        # SSE 流式响应
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # ---- SPA 静态文件 ----
    root /path/to/voidswitch-dashboard/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # 指纹资源长期缓存
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    location = /index.html {
        add_header Cache-Control "no-cache";
    }
}
```

### SSL（HTTPS）

生产环境建议用 certbot 或 acme.sh 自动管理证书，或把 443 端口写在 nginx 里：

```nginx
server {
    listen 443 ssl;
    server_name voidswitch.example.com;

    ssl_certificate     /etc/letsencrypt/live/voidswitch.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/voidswitch.example.com/privkey.pem;

    # 同上 location 块…
}

# HTTP → HTTPS 跳转
server {
    listen 80;
    server_name voidswitch.example.com;
    return 301 https://$host$request_uri;
}
```

## Caddy

```caddy
voidswitch.example.com {
    # 聊天请求体较大
    request_body {
        max_size 25MB
    }

    # API 反代（所有后端路径）
    @api path /v1/* /api/* /provider-api/* /healthz /install /install.sh /install.ps1 /swagger /docs /redoc /openapi.json
    reverse_proxy @api 127.0.0.1:8080 {
        # 透传客户端真实 IP/协议
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
        header_up X-Forwarded-Host {host}

        # SSE 流式响应
        flush_interval -1
    }

    # SPA 静态文件
    root * /path/to/voidswitch-dashboard/dist
    try_files {path} /index.html

    # 指纹资源长期缓存
    header /assets/* Cache-Control "public, immutable"
    header /assets/* Expires "+1 year"
    header /index.html Cache-Control "no-cache"

    # 自动 HTTPS
    tls your@email.com
}
```

Caddy 会自动申请和续签 Let's Encrypt 证书，`tls` 指令中的邮箱用于 ACME 注册。
如果不想要自动 HTTPS（例如前面已有 CDN），可改为 `tls internal` 或省略。

##  Cloudflare Tunnel

如果你用 `cloudflared` 把内网服务暴露到公网，只需把 Tunnel 指向 nginx/Caddy 的
监听地址（例如 `http://localhost:80`）即可。VoidSwitch 会通过 `X-Forwarded-Proto`
头识别客户端真实协议，回调地址会自动生成正确的 `https://` URL。
