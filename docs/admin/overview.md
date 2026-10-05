# 管理概览

本部分适用于**管理人员** — 运营平台的 owner、co-owner 和 admin。
如果你是成员，[指南](/guide/introduction)涵盖了你需要的一切。

## 权限层级

VoidSwitch 在后端强制执行四个层级，并在 UI 中反映。梯度从低到高：
`member < 身份组管理员 < 管理人员 < 所有者`。

| 层级 | 角色 | 范围 |
| ---- | ----- | ----- |
| **成员** | member | 仅限自己的资源（自己的令牌、自己的日志/用量）。 |
| **身份组管理员** | 由[身份组](/admin/role-groups) `grants="admin"` 映射派生 | 只读观察者：只能查看**自己所管理的身份组**的用户、统计、日志和审计日志。不隐含平台角色，也不含模型调用权。 |
| **管理人员** | owner、co-owner、admin | 日常管理界面：供应商、密钥、节点/节点组、模型、身份组（**只读**，仅 owner 可编辑）、用户列表、日志、设置和发布公告。 |
| **所有者** | owner、co-owner | 在管理人员基础上的敏感操作。 |

### 仅限所有者的（敏感）操作

保留给 owner 和 co-owner：

- 禁用用户和切换全局 Void-Token；
- 删除供应商和管理每个供应商的密钥管理 API；
- 显示审计机密（明文密钥、令牌、公告编辑历史）；
- **创建 / 编辑 / 删除身份组**（包括临时移除成员）；
- **查看请求日志中的 request / response body**（headers 和 debug 尝试 admin 与身份组管理员也可看）；
- **编辑**系统设置和执行**"立即清理日志"**（管理员只能*查看*只读设置）。

## 角色的来源

平台层级来源于用户在 Prism 上配置的**主团队**中的角色
（`main_team_id`）：团队的 **owner → owner**，**co-owner → co-owner**，
**admin → admin**。这是从 Prism 获取层级的*唯一*来源 — Prism 的
**实例 / 站点范围**管理员**不**被信任（成为 Prism 系统管理员并不意味着你是
VoidSwitch 管理员），其他团队也从不会授予层级（它们仍然可以授予[身份组](/admin/role-groups)用于模型访问）。

- **Owner / co-owner** 来自主团队的 owner/co-owner 角色，或显式的
  `owner_subs` / `owner_emails` 授予（或首个用户引导）。它们不能从控制台分配。
- **Admin** 来自主团队的 `admin` 角色，或可由 owner 在[用户](/admin/users)页面上
  本地授予（"本地管理员覆盖"）。
- **Member** 是任何其他有平台访问权限的用户的默认角色。

## 管理页面

| 页面 | 层级 | 功能 |
| ---- | ---- | ----------- |
| [供应商](/admin/providers) | 管理人员 | 添加上游平台及其模型。 |
| [上游密钥](/admin/keys) | 管理人员 | 加载和管理每个供应商的 API 密钥。 |
| [节点与节点组](/admin/proxies) | 管理人员 | 配置出口节点与节点组。 |
| [模型](/admin/models) | 管理人员 | 管理模型目录和访问权限。 |
| [身份组](/admin/role-groups) | 管理人员（只读）/ 所有者 | 将团队角色映射到模型访问权限或身份组管理员。 |
| [用户](/admin/users) | 管理人员/所有者 | 查看用户；授予 admin / 禁用（所有者）。 |
| [Void-Token](/admin/tokens) | 所有者 | 跨用户管理客户端令牌。 |
| [设置](/admin/settings) | 管理人员/所有者 | 调整运维阈值。 |
| [审计与机密](/admin/audit) | 管理人员/所有者 | 审查记录；显示机密信息。 |

## 数据库连接池

PostgreSQL 部署可通过环境变量调整每个 worker 的连接池：
`VOIDSWITCH_DATABASE__POOL_SIZE`（默认 15）、
`VOIDSWITCH_DATABASE__MAX_OVERFLOW`（默认 5）、
`VOIDSWITCH_DATABASE__POOL_TIMEOUT`（默认 15 秒）、
`VOIDSWITCH_DATABASE__POOL_RECYCLE`（默认 1800 秒）和
`VOIDSWITCH_DATABASE__POOL_PRE_PING`（默认 true）。连接 URL 不能替代这些
SQLAlchemy pool 参数。理论连接上限为 `worker 数 × (pool_size + max_overflow)`；
请在 PostgreSQL `max_connections` 中为管理连接和其他服务预留余量。

SQLite 不使用这些队列池容量参数；它保持当前驱动的默认池行为，重点应放在减少
并发写入和锁等待，而不是增加连接数。

## Redis

Python 网关必须连接 Redis。Redis 保存跨 worker 的短期缓存和协调状态：滑动窗口限流、
设置快照通知、供应商 OAuth 登录状态和刷新锁、SSE/后台任务租约、密钥与上游会话固定，
以及动态上游健康统计。用户、密钥、路由、日志和冷却状态仍以数据库为准。

Docker Compose 会启动内部 `redis` 服务，默认连接为 `redis://redis:6379/0`。使用托管
Redis 时设置 `VOIDSWITCH_REDIS_URL`；多个部署共用实例时，为每个部署设置不同的
`VOIDSWITCH_REDIS_KEY_PREFIX`。跨不可信网络时使用 `rediss://`，不要公开 Redis 端口，
也不要在日志或截图中暴露含密码的 URL。

Redis 只存临时状态，因此 Compose 默认关闭 RDB/AOF。Redis 重启会重置限流窗口、租约、
会话固定和动态健康统计，但不会丢失业务数据。Redis 无法连接时应用拒绝启动；运行中限流、
OAuth 协调和租约操作采用安全失败，路由健康数据则回退到中性排序。

`redis.max_connections` 是每个 worker 的上限，总连接上限约为
`worker 数 × max_connections`。多 worker 部署还应使用 PostgreSQL；SQLite 不适合横向扩展。
