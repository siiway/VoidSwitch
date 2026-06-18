# VoidSwitch 代码审查报告

> 审查范围：`backend/`（Python/FastAPI）和 `frontend/`（React/TypeScript）
>
> 严重程度：🔴 blocking / 🟡 important / 🟢 nit

---

## 后端（Python/FastAPI）

### 🔴 [blocking]

#### 1. `dispatcher.py` 内部嵌套数据库会话

`dispatch()` (`dispatcher.py:375`) 在调用方已持有中间件作用域会话的情况下，自行调用 `async with db.session()`。认证阶段通过中间件会话完成，而转发逻辑使用全新会话。

- **风险**：认证后到转发前，密钥/提供商状态可能在另一会话中被修改（TOCTOU）。
- **`_persist_stream_usage`** (`dispatcher.py:1110`) 在 `asyncio.shield()` 内部再次打开全新会话——数据库不可用时静默吞掉异常，使用量数据完全丢失。

#### 2. `_rpm_window` 进程内限速器 (`proxy.py:38`)

```python
_rpm_window: dict[int, deque[float]] = defaultdict(deque)
```

多个 uvicorn 工作进程下各自独立计数，限速器实际效果为 per-worker 而非全局。

### 🟡 [important]

#### 1. `dispatch()` 函数过长（273 行）

`dispatcher.py:375-648` 包含提供商选择、密钥迭代、重试循环、成功/失败处理等全部逻辑。建议将提供商枚举、密钥遍历和单次尝试循环提取为独立命名函数。

#### 2. `ModelEntry.allowed_role_group_ids` 类型应为 `list[int]`

`models/db.py:153`——当前为 `Mapped[list[Any]]`，但模式和使用方式均为 `int`。

#### 3. `probe_route` 每次创建新客户端（`network.py:121-146`）

代理健康检查每次调用都新建 `httpx.AsyncClient`，浪费 TLS 连接。建议复用 `ClientPool`。

#### 4. `_ADDED_COLUMNS` 仅支持 additive 变更（`database.py:87-130`）

列重命名、类型更改或删除将导致数据库损坏。需记录此限制并制定正式迁移策略。

#### 5. OAuth PKCE 状态在进程内（`auth.py:113-133`）

多 uvicorn 工作进程下登录状态丢失 → 用户看到 "Unknown or expired login state"。

### 🟢 [nit]

1.  `main.py:21-50` 每个 `import` 写一个 `from ... import (...)` 块——建议合并。
2.  `auth.py:57-62` `CO_OWNER` 和 `OWNER` 同等级（rank 3），同层级间无法管理彼此资源。属有意设计。
3.  `proxy.py:293-346` 原始模型与别名路由的列表构建代码重复——建议提取为辅助函数。

---

## 前端（React/TypeScript）

### 🔴 [blocking]

#### 1. `as unknown as RequestLogDetail` 类型绕过（`Logs.tsx:240`）

```typescript
setDetailLog(r as unknown as RequestLogDetail);
```

API 变更后静默产生损坏对象。建议至少添加运行时形状断言或 Zod 校验。

#### 2. 内联 CSS 变量替代 Fluent Token（`ui.tsx:184-186`）

```typescript
backgroundColor: "var(--colorPaletteRedBackground3)",
```

Fluent UI 实现细节可能跨大版本变化。应使用 `tokens.colorPaletteRedBackground3`。

### 🟡 [important]

#### 1. 权限逻辑在前端硬编码重复（`AuthContext.tsx:72-73`）

```typescript
const isOwner = user?.role === "owner" || user?.role === "co-owner";
const isStaff = isOwner || user?.role === "admin";
```

应与后端共享常量 `OWNER_ROLES`/`STAFF_ROLES`，避免角色检查不一致。

#### 2. `parseRoutes()` 分隔符解析脆弱（`Providers.tsx:105-131`）

`lastIndexOf(" @ ")` 和 `indexOf(" => ")`——若别名文本包含 ` @ ` 则解析错误。建议使用 JSON 或转义格式。

#### 3. `useIdJump` 200ms 超时清除高亮（`Logs.tsx:87-132`）

用户在 200ms 间隙内交互则高亮立即消失。建议监听容器的 `scroll` 事件替代。

### 🟢 [nit]

1.  `Settings.tsx:136` `values.proxy_switching_enabled !== false` 将 `undefined` 视为启用——正确行为，建议显式注释。
2.  `api/client.ts:8-12` `API_BASE` 回退到 `window.location.origin`——简洁准确地与单来源部署配合。

---

## 架构评价

| 维度 | 评价 |
|------|------|
| **转发引擎** | 提供商→密钥→路由迭代 + 按错误类型分类（网络→代理、认证→密钥、限流→轮转）设计合理 |
| **会话中间件** | `RequestSessionMiddleware` 在响应体发送前提交——优雅解决陈旧数据竞态 |
| **客户端池** | `ClientPool` 按 `(proxy, local_address, timeout)` 缓存——连接复用效果好 |
| **Go 重写** | 忠实镜像 Python 架构（Gin↔FastAPI，GORM↔SQLAlchemy） |
| **流式使用量** | 流结尾的 `_persist_stream_usage` 无重试、无队列——单点脆弱 |

### 优先级最高的三项

1. **流使用量持久化静默失败** —— `_persist_stream_usage` 在 `asyncio.shield()` 内无重试，数据丢失不可追溯。
2. **`dispatch()` 嵌套独立会话** —— 认证与转发操作不同事务，存在 TOCTOU 窗口。
3. **OAuth 状态 / 限速器进程内** —— 多工作进程部署时功能异常（状态丢失、限速失效）。
