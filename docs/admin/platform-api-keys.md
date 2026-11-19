# 平台 API Key

**平台 API Key**（`vsapi-…`）是管理人员（owner / co-owner / admin）专用的自动化
凭据。一把 Key 同时驱动两个入口：

| 入口 | 地址 | 用途 |
| --- | --- | --- |
| REST | `/api/v1/**` | 与 MCP 工具一一对应的 HTTP 接口 |
| MCP | `/api/v1/mcp` | MCP Streamable HTTP，供 AI Agent 调用 |

它与 [Void-Token](/admin/tokens) 完全分离：Void-Token 只能调用网关（`/v1`），
平台 API Key 只能调用管理面，两者互不通用。

## 创建与 scope

控制台侧边栏 → **平台 API Key** → **创建 API Key**。密钥明文只显示一次，创建后
可与调用指南一起复制。

每把 Key 携带一组 **scope**，写法是 `分类.动作`（例如 `model.edit`）：

| scope 写法 | 含义 |
| --- | --- |
| `read` | 所有只读动作 |
| `model.*` | 整个分类 |
| `model.edit` | 单个动作 |
| `provider-key:acme.*` | 该提供商（slug 为 `acme`）的上游密钥管理 |

**Key 的权限 = 自己的 scope ∩ 拥有者当前角色的可授予范围。** 因此：

- 创建时只能勾选自己角色有权限的项（所有者才有提供商密钥管理与删除提供商）；
- 角色被降级后，超出新范围的 scope 立即失效，无需改动 Key；
- 失去管理人员身份时该用户的全部 Key 会被停用（状态显示"已停用 —— 失去管理人员权限"），**重新获得身份后需要手动启用**，不会静默恢复。

## 两个硬性限制

- **无法读取任何已存储的机密。** 不存在 `*.reveal` 动作：上游密钥明文、审计敏感
  载荷、Void-Token 明文都无法通过平台 API Key 获取。
- **仅管理人员可用。** 非 staff 用户调用会被直接拒绝（403），即便 Key 行仍为启用。

## 调用示例

### MCP 客户端

```json
{
  "mcpServers": {
    "voidswitch": {
      "type": "http",
      "url": "https://voidswitch.example.com/api/v1/mcp",
      "headers": { "Authorization": "Bearer vsapi-…" }
    }
  }
}
```

`tools/list` 返回的正是该 Key 的 scope 覆盖的工具集合，工具名是 `vs_` 加 scope
把点换成下划线（`model.edit` → `vs_model_edit`）。不在 scope 内的工具根本不出现在
列表里。

### REST

```bash
curl -s https://voidswitch.example.com/api/v1/whoami \
  -H "Authorization: Bearer vsapi-…"

curl -s https://voidswitch.example.com/api/v1/models \
  -H "Authorization: Bearer vsapi-…"
```

`/whoami` 返回拥有者、角色、生效 scope 与可调用的动作，适合在发正式请求前自检。

### Python SDK

仓库内附带 SDK（`sdk/python`）：

```python
from voidswitch import Client

vs = Client("https://voidswitch.example.com", api_key="vsapi-…")
for model in vs.models.list():
    print(model["model_id"], model["enabled"])
```

## 限流

平台 API 按 **每个 Key** 计数，默认 20 秒 30 次，可在[设置](/admin/settings)的
**平台 API** 分组调整（`0` 表示不限）。超限返回 `429`。

## 审计

通过平台 API Key 执行的操作照常写入[审计记录](/admin/audit)，并额外记录：

- **凭据** —— 该 Key 的指纹（`vsapi-ab12cd…wxyz`）；
- 详情中的 `via` —— `rest` 或 `mcp`。

因此"谁、用哪把 Key、通过哪种协议做了什么"都能从一条记录里读出来。
