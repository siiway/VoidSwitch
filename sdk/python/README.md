# VoidSwitch Python SDK

调用 VoidSwitch **平台 API**（`/api/v1`）的 Python 客户端。一把平台 API Key
（`vsapi-…`）同时可用于该 REST 接口与 MCP 端点 `/api/v1/mcp`；能做什么取决于
该 Key 的 scope。

本目录尚未发布到 PyPI，直接以源码方式引入即可。

## 安装

```bash
pip install -e sdk/python
```

或直接把 `sdk/python` 加入 `PYTHONPATH`。

## 取一把 Key

控制台 → **平台 API Key** → 创建，勾选需要的 scope。Key 明文只显示一次。

## 快速开始

```python
from voidswitch import Client

vs = Client("https://voidswitch.example.com", api_key="vsapi-…")

print(vs.whoami())          # 拥有者、角色、scope、可调用的动作

for model in vs.models.list():
    print(model["model_id"], model["enabled"])
```

## 常用操作

```python
# 模型
vs.models.upsert("fast-coder", display_name="Fast Coder", enabled=True,
                 allowed_role_group_ids=[3])
vs.models.batch(["fast-coder", "slow-coder"], enabled=False)
vs.models.get_route("fast-coder")
vs.models.put_route("fast-coder", upstreams=[
    {"provider_id": 4, "upstream_model": "gpt-4o", "position": 1, "weight": 1},
])
vs.models.clear_cooldown("fast-coder")

# 提供商（密钥字段可选，先建空提供商再补密钥）
p = vs.providers.create("Acme", "openai")
vs.provider_keys.add("acme", ["sk-abc # alice", "sk-def"])
vs.provider_keys.refresh_balance("acme")

# 日志
page = vs.request_logs.list(limit=20, success=False)
detail = vs.request_logs.get_debug(page["items"][0]["id"])

# 审计（不含任何 reveal 操作）
vs.audit_logs.list(action="model.edit", limit=50)

# 设置
vs.settings.update({"logs_page_size": 100})
```

## 错误处理

所有失败都抛出 `VoidSwitchError` 的子类，`detail` 是服务端原文：

```python
from voidswitch import Client, PermissionError, RateLimitError

try:
    vs.providers.delete(4)
except PermissionError as e:
    print("scope 不足:", e.detail)
except RateLimitError:
    print("触发平台 API 限流，退避后重试")
```

| 异常 | HTTP |
| --- | --- |
| `UnauthorizedError` | 401 |
| `PermissionError` | 403 |
| `NotFoundError` | 404 |
| `InvalidRequestError` | 422 |
| `RateLimitError` | 429 |
| `TransportError` | 网络层失败 |

## 约定

- 每个方法就是一次 HTTP 请求，返回值是服务端 JSON 原样（`dict` / `list`），因此
  服务端新增字段不会让 SDK 失效。
- Key 管理类接口（`provider_keys.*`）按**提供商 slug** 定位，因为 scope 里写的是
  slug：`provider-key:acme.*`。
- 平台 API 按 Key 限流，默认 20 秒 30 次，可在设置的「平台 API」分组调整。
