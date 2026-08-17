# voidswitch-agent（VS 专属中继）

当你的 VoidSwitch 需要出海访问 AI 服务时，通用的 HTTP / SOCKS 正向代理协议
往往容易被标记或阻断。**voidswitch-agent** 是 VoidSwitch 专属的轻量中继：部署在
干净海外 IP 上，用自有的鉴权 + 传输协议接收网关的出站请求，再转发到真正的上游。

- 高并发、低占用：Go 静态单二进制（约 6–10 MB），HTTP/2 多路复用，
  goroutine-per-stream，上游共享连接池。
- 专属鉴权：每实例一个预共享 token（安装时生成），不是公开代理，不易被滥用/标记。
- 路径优化：上游连接池 + keep-alive/H2（降低首字节延迟）、可选绑定源 IP、
  SNI/链式代理出口策略。

## 工作方式

```
VoidSwitch  ──(token 鉴权 + X-VS-Upstream-URL)──►  agent  ──►  上游 AI 服务
```

- **relay 模式（默认，主路径）**：网关把出站请求连同 `X-VS-Upstream-URL` 目标头
  发给 agent；agent 剥离该头、去掉 hop-by-hop 头与 token，经共享 HTTP/2 连接池
  转发，并流式回传（SSE 安全）。
- **connect 模式（兜底）**：`--mode connect` 让 agent 退化成标准 HTTP CONNECT
  正向代理（token 作代理认证），零改动即可用。

## 安装（三种方式）

**方式一 · 一行安装（推荐）**

```bash
curl -fsSL https://…/install.sh | sh
```

脚本自动识别架构下载二进制、生成随机 token、写 systemd unit，并打印接入信息
（地址 + token），可直接粘贴到 VoidSwitch 的节点页。

**方式二 · Docker**

```bash
docker run -d --name vs-agent -p 8443:8443 \
  -e VOIDSWITCH_AGENT_TOKEN=$(openssl rand -hex 24) \
  ghcr.io/siiway/voidswitch-agent
```

**方式三 · 手动**

```bash
./voidswitch-agent --token "$(openssl rand -hex 24)"
```

## 配置

详见 `agent/README.md`。常用项：

| 参数 | 环境变量 | 默认 | 说明 |
| --- | --- | --- | --- |
| `--listen` | `VOIDSWITCH_AGENT_LISTEN` | `:8443` | 监听地址 |
| `--token` | `VOIDSWITCH_AGENT_TOKEN` | 必填 | 预共享 token |
| `--tls-cert`/`--tls-key` | `…_TLS_CERT`/`…_TLS_KEY` | 空 | TLS 证书。留空即明文（建议由 Caddy/nginx 终止 TLS） |
| `--mode` | `…_MODE` | `relay` | `relay` 或 `connect` |
| `--upstream-proxy` | `…_UPSTREAM_PROXY` | 空 | 出口链式代理 |
| `--bind-address` | `…_BIND_ADDRESS` | 空 | 绑定出口源 IP |
| `--allowlist-ips` | `…_ALLOWLIST_IPS` | 空 | 允许连接的 CIDR 白名单 |

## 接入 VoidSwitch

在 VoidSwitch 的 **节点与节点组** 页新增一个 **agent** 节点：

- **URL**：agent 地址，如 `https://agent.example.com:8443`
- **Token**：预共享 token（服务端加密存储，仅 owner 可 reveal）

经过该节点的请求会使用自定义中继协议发给 agent。该节点照常参与节点组的健康
巡检与动态排序。完整路由说明见 [节点与节点组](./proxies.md)。

## 安全

- token 恒定时间比较；可选 CIDR 白名单。
- token 永不转发给上游。
- 不记录请求体，仅记 method / host / status / 耗时。
