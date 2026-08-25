"""SQLAlchemy 2.0 async ORM models."""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

from voidswitch.constants import (
    KeySelectMode,
    KeyStatus,
    NodeStatus,
    NodeType,
    Role,
)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _new_uuid() -> str:
    return str(uuid_lib.uuid4())


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), default=None)
    email: Mapped[str | None] = mapped_column(String(320), default=None, index=True)
    name: Mapped[str | None] = mapped_column(String(255), default=None)
    picture: Mapped[str | None] = mapped_column(Text, default=None)
    role: Mapped[str] = mapped_column(String(32), default=Role.MEMBER.value)
    # The user's role in the configured main team (Prism), snapshotted at login:
    # "owner" / "co-owner" / "admin" / "member" / None. Used for display and to
    # flag a "local admin override" (a VoidSwitch admin who is not a main-team
    # admin). Not the user's instance/site-wide Prism role.
    prism_role: Mapped[str | None] = mapped_column(String(32), default=None)
    # The user's Prism team ids (snapshot at login). Surfaced for users who are
    # not in the configured main team, so the dashboard can show which team(s)
    # placed them in their role group(s).
    team_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Bumped whenever every existing dashboard session must be invalidated (e.g.
    # an owner disables the account). A session JWT carries the epoch it was
    # minted at; a mismatch is rejected, forcing a fresh login.
    session_epoch: Mapped[int] = mapped_column(Integer, default=0)
    login_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    login_token_prefix: Mapped[str | None] = mapped_column(String(32), default=None)
    # Set when an owner disables the account: the user's Void-Tokens are turned
    # off and this flag remembers to turn them back on at the user's next login
    # (after the account is re-enabled), so re-enabling forces a role re-eval.
    void_tokens_admin_disabled: Mapped[bool] = mapped_column(Boolean, default=False)

    tokens: Mapped[list[VoidToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    group_memberships: Mapped[list[RoleGroupMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class VoidToken(Base, TimestampMixin):
    __tablename__ = "void_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="default")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(32), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Empty list means "all models permitted".
    allowed_models: Mapped[list[str]] = mapped_column(JSON, default=list)
    rpm_limit: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited
    daily_quota: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited (requests/day)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # When enabled, all requests using this token record full request/response
    # detail (headers, body) for debugging.
    debug_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="tokens", lazy="selectin")

    @property
    def username(self) -> str | None:
        """Human-friendly owner label for API output."""
        user = self.user
        if user is None:
            return None
        label = user.username or user.name or user.email
        return f"{label}#{user.id}" if label else None


class ExposedModel(Base, TimestampMixin):
    """An *exposed* model — the only model ids clients ever see or call.

    ``model_id`` is the public id (e.g. ``fast-coder``, ``astr-chat``). It has
    no direct link to a specific provider: dispatcher routing resolves it through
    :class:`Route` → :class:`RouteLayer` → :class:`RoutePoolEntry` to reach the
    real upstream (``slug/model`` refs which are never advertised). Structured
    metadata fields here feed the OpenCode plugin config block and the
    ``/v1/models`` payload. Field precedence when building the downstream config:
    explicit structured fields > ``opencode_config`` (custom JSON) > models.dev
    placeholder > defaults.
    """

    __tablename__ = "exposed_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # Custom OpenCode model config (deep-merged below the structured fields).
    opencode_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # When False the model is hidden from the advertised list (/v1/models) and
    # the OpenCode picker.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Role groups whose members may call this model. The built-in "moderator"
    # group (owner/co-owner/admin) is always allowed and is *not* listed here.
    allowed_role_group_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    # Structured metadata (override opencode_config when set).
    limit_context: Mapped[int | None] = mapped_column(Integer, default=None)
    limit_input: Mapped[int | None] = mapped_column(Integer, default=None)
    limit_output: Mapped[int | None] = mapped_column(Integer, default=None)
    reasoning: Mapped[bool | None] = mapped_column(Boolean, default=None)
    # Capabilities {"text","image","audio","tool"} booleans + modalities JSON.
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    modalities: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    # models.dev mapping: the matched registry id + when it was last synced.
    models_dev_id: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    models_dev_synced_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Who first registered metadata for this model (id + display-name snapshot).
    added_by: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    added_by_name: Mapped[str | None] = mapped_column(String(255), default=None)

    route: Mapped[Route | None] = relationship(
        back_populates="exposed_model", cascade="all, delete-orphan",
        uselist=False, lazy="selectin",
    )


class Route(Base, TimestampMixin):
    """The dispatch flowchart for one exposed model.

    Top of the flow is the user-requested model; below it sit ordered
    :class:`RouteLayer` fallback pools (position 0 first). Each layer is a pool
    of upstream :class:`RoutePoolEntry` refs tried with weighted randomness.
    """

    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exposed_model_id: Mapped[int] = mapped_column(
        ForeignKey("exposed_models.id", ondelete="CASCADE"), unique=True, index=True
    )

    exposed_model: Mapped[ExposedModel] = relationship(
        back_populates="route", lazy="selectin"
    )
    layers: Mapped[list[RouteLayer]] = relationship(
        back_populates="route",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RouteLayer.position",
    )


class RouteLayer(Base):
    """One fallback pool of a route flowchart (ordered by ``position``).

    ``max_attempts`` is how many of this layer's entries are tried (in weighted
    order) before falling through to the next layer: 1 = pick one at random;
    >1 = try up to that many (all entries if attempts ≥ entry count).
    """

    __tablename__ = "route_layers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(
        ForeignKey("routes.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)

    route: Mapped[Route] = relationship(back_populates="layers", lazy="selectin")
    entries: Mapped[list[RoutePoolEntry]] = relationship(
        back_populates="layer",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RoutePoolEntry.id",
    )


class RoutePoolEntry(Base):
    """One upstream reference inside a route layer pool.

    Points at a provider (by id) and the exact ``upstream_model`` it should be
    called with (provider slug + model, e.g. ``deepseek/deepseek-v4-flash``).
    ``key_pool`` optionally restricts dispatch to keys carrying that pool tag.
    """

    __tablename__ = "route_pool_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    layer_id: Mapped[int] = mapped_column(
        ForeignKey("route_layers.id", ondelete="CASCADE"), index=True
    )
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("providers.id", ondelete="SET NULL"), default=None, index=True
    )
    upstream_model: Mapped[str] = mapped_column(String(255), default="")
    weight: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    key_pool: Mapped[str] = mapped_column(String(64), default="")

    layer: Mapped[RouteLayer] = relationship(back_populates="entries", lazy="selectin")
    provider: Mapped[Provider | None] = relationship(lazy="joined")


class Provider(Base, TimestampMixin):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Stable public identifier, independent of the autoincrement primary key.
    # Used by the mounted provider key-management API so external integrations
    # reference a provider by an opaque, non-guessable id.
    uuid: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, default=_new_uuid
    )
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    # Stable internal slug applied to this provider's upstream model ids
    # ("slug/model"), used as the internal model index — never advertised.
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, default="")
    # Outbound node group this provider's upstream requests use; null = the
    # global default group.
    node_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("node_groups.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    # Adapter key, e.g. "openai", "anthropic", "deepseek".
    type: Mapped[str] = mapped_column(String(64), default="openai")
    base_url: Mapped[str] = mapped_column(String(512), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower = preferred
    weight: Mapped[int] = mapped_column(Integer, default=1)
    # Supported model names / glob patterns ("*" matches anything).
    models: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Optional remap of inbound model name -> upstream model name.
    model_map: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Alias routes: each {"alias", "upstream", "pool"} maps an inbound model name
    # to an upstream model served by a specific key pool. Lets e.g.
    # "deepseek-v4-flash-lkd" → "deepseek-v4-flash" on the "leaked" key pool, while
    # "deepseek-v4-flash" → same upstream on the "members" pool. See ApiKey.pool.
    model_routes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    balance_url: Mapped[str | None] = mapped_column(String(512), default=None)
    extra_headers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=0)  # 0 = use global
    # "200 OK + 0 tokens" auto-retry: when True, a 200 response that carries no
    # usage is treated as a transient upstream fault (retried through the
    # failover machinery, never cached). Such providers also use the shared
    # response cache (memory → disk → drop) so a degenerate empty reply can be
    # replaced by the last good cached response for the same request.
    retry_on_zero_token: Mapped[bool] = mapped_column(Boolean, default=False)
    # claude-code masquerade only: when True, drop the inbound client's entire
    # "You are OpenCode…" system block instead of scrubbing it in place.
    drop_opencode_identity_block: Mapped[bool] = mapped_column(Boolean, default=False)
    # How this provider picks which upstream key to lead with for each request:
    # "round_robin" | "random" | "fallback" | "pinned_round_robin" |
    # "pinned_random". See constants.KeySelectMode.
    key_select_mode: Mapped[str] = mapped_column(
        String(32), default=KeySelectMode.ROUND_ROBIN.value
    )
    # How long (seconds) a key rate-limited by this provider stays out of the pool
    # before it can be retried, when the upstream's 429 carries no ``Retry-After``
    # header. 0 = fall back to the global ``rate_limit_recovery_seconds`` setting.
    rate_limit_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=0)
    # Who created this provider (id + a display-name snapshot). Lets members
    # manage only the providers they added; null for legacy/seeded rows.
    added_by: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    added_by_name: Mapped[str | None] = mapped_column(String(255), default=None)
    # Optional per-provider "key-management API key": a programmatic credential
    # that grants access to manage *this provider's* upstream keys through the
    # mounted key-management sub-app. Disabled by default; only (co-)owners may
    # enable, rotate, or reveal it. ``key_api_token_hash`` is the lookup hash,
    # ``key_api_token_ciphertext`` the at-rest encrypted plaintext (so owners can
    # reveal it later), and ``key_api_token_preview`` a short non-secret label.
    key_api_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    key_api_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, default=None
    )
    key_api_token_ciphertext: Mapped[str | None] = mapped_column(Text, default=None)
    key_api_token_preview: Mapped[str | None] = mapped_column(String(48), default=None)

    keys: Mapped[list[ApiKey]] = relationship(
        back_populates="provider", cascade="all, delete-orphan", lazy="selectin"
    )


class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("provider_id", "key_hash", name="uq_provider_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("providers.id", ondelete="CASCADE"), index=True
    )
    key_ciphertext: Mapped[str] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(String(64), index=True)
    key_preview: Mapped[str] = mapped_column(String(32), default="")
    # Optional pool tag, e.g. "leaked" / "members". Empty = untagged. A model
    # route with a matching pool restricts dispatch to keys carrying that tag.
    pool: Mapped[str] = mapped_column(String(64), default="", index=True)
    # Manual ordering position (lower = earlier). Drives the "fallback" key-select
    # mode and the base order the other modes rotate/shuffle over. Drag-sortable
    # from the dashboard.
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(32), default=KeyStatus.ACTIVE.value, index=True)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str | None] = mapped_column(String(255), default=None)
    balance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    disabled_reason: Mapped[str | None] = mapped_column(String(255), default=None)
    # When the key was first moved out of the active state (insufficient balance,
    # invalid, etc.). Used to age out long-dead keys (e.g. "no balance for N days")
    # and cleared whenever the key is re-enabled. Null while active.
    disabled_since: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # When a rate-limited (429) key may re-enter the candidate pool. Derived from
    # the upstream's ``Retry-After`` header when present, else the provider/global
    # cooldown. Null while the key is not rate-limited; cleared on recovery.
    rate_limit_until: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Who added this key (id + a display-name snapshot). Lets members manage
    # only the keys they added; null for legacy/seeded rows.
    added_by: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    added_by_name: Mapped[str | None] = mapped_column(String(255), default=None)

    provider: Mapped[Provider] = relationship(back_populates="keys", lazy="selectin")


class Node(Base, TimestampMixin):
    """One outbound node (replaces the old ``Proxy``).

    A node is a concrete egress hop VoidSwitch can issue a request through.
    ``type`` selects the transport: plain HTTP/SOCKS forward proxy, a
    voidswitch-agent relay, or Direct (``url`` empty). Nodes belong to
    :class:`NodeGroup`\\ s which own the routing order.
    """

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # e.g. http://user:pass@host:port, socks5://host:port, or an agent address.
    # Empty = Direct node.
    url: Mapped[str] = mapped_column(String(512), default="", unique=True)
    type: Mapped[str] = mapped_column(String(16), default=NodeType.HTTP.value)
    # Agent-node credential (encrypted, like upstream key secrets). Never plain.
    token_ciphertext: Mapped[str | None] = mapped_column(Text, default=None)
    # Bind outbound sockets to this local source IP (httpx local_address).
    local_address: Mapped[str | None] = mapped_column(String(64), default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(
        String(32), default=NodeStatus.ACTIVE.value, index=True
    )
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[float | None] = mapped_column(Float, default=None)
    # Exponentially-weighted moving average of latency (ms) used for the
    # node-group dynamic ordering.
    latency_ewma: Mapped[float | None] = mapped_column(Float, default=None)
    note: Mapped[str | None] = mapped_column(String(255), default=None)
    disabled_reason: Mapped[str | None] = mapped_column(String(255), default=None)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class NodeGroup(Base, TimestampMixin):
    """A freely-created group of outbound nodes used by the routing system.

    A group picks *nodes* from the global pool and/or *inherits* the members of
    other groups (live reference, like Python class inheritance). Each group may
    define its own idle probe URL + interval; ``slug="system"`` is the special
    system-request group (only (co-)owners may edit its nodes), and
    ``slug="default"`` is the group used by providers with no explicit
    ``node_group_id``.
    """

    __tablename__ = "node_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str | None] = mapped_column(String(64), unique=True, default=None)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    probe_url: Mapped[str | None] = mapped_column(String(512), default=None)
    # 0 = fall back to the global node_probe_interval_seconds.
    probe_interval_seconds: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    members: Mapped[list[NodeGroupMember]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="NodeGroupMember.id",
        foreign_keys="NodeGroupMember.group_id",
    )


class NodeGroupMember(Base):
    """One row of a group: a direct node OR an inherited group (never both)."""

    __tablename__ = "node_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "node_id", name="uq_group_node"),
        UniqueConstraint("group_id", "source_group_id", name="uq_group_source_group"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("node_groups.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[int | None] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), default=None, index=True
    )
    source_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("node_groups.id", ondelete="CASCADE"), default=None, index=True
    )
    weight: Mapped[int] = mapped_column(Integer, default=1)

    group: Mapped[NodeGroup] = relationship(
        back_populates="members", lazy="selectin", foreign_keys="NodeGroupMember.group_id"
    )
    node: Mapped[Node | None] = relationship(lazy="joined")
    source_group: Mapped[NodeGroup | None] = relationship(
        lazy="joined", foreign_keys=[source_group_id]
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class ModelsDevCache(Base):
    """Cached models.dev registry entry (id → raw JSON).

    Populated by the periodic sync (see ``services.models_dev``); used as
    placeholder metadata for exposed models matched to a registry id. Keyed by
    the registry model id; ``updated_at`` drives the sync cadence.
    """

    __tablename__ = "models_dev_cache"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class RoleGroup(Base, TimestampMixin):
    """A named "身份组" that determines which models its members may call.

    The built-in ``moderator`` group (``builtin=True``, ``slug="moderator"``) is
    seeded on first boot, always grants access to every model, and may not be
    deleted. Custom groups gate access to the specific models that list them in
    ``ExposedModel.allowed_role_group_ids``. Membership is recomputed at every
    login from the team→role mappings below.
    """

    __tablename__ = "role_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Stable identifier for the built-in group ("moderator"); null for custom.
    slug: Mapped[str | None] = mapped_column(String(64), unique=True, default=None)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)

    mappings: Mapped[list[RoleGroupMapping]] = relationship(
        back_populates="group", cascade="all, delete-orphan", lazy="selectin"
    )
    memberships: Mapped[list[RoleGroupMembership]] = relationship(
        back_populates="group", cascade="all, delete-orphan", lazy="selectin"
    )


class RoleGroupMapping(Base):
    """Auto-assignment rule: members of a Prism team at/above a role get the group.

    At login the user's effective role in ``team_id`` is compared against
    ``min_role`` (using ``constants.TEAM_ROLE_RANK``); a role that ranks equal or
    higher grants membership of ``group``.
    """

    __tablename__ = "role_group_mappings"
    __table_args__ = (
        UniqueConstraint("role_group_id", "team_id", "min_role", name="uq_group_team_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_group_id: Mapped[int] = mapped_column(
        ForeignKey("role_groups.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[str] = mapped_column(String(120), index=True)
    min_role: Mapped[str] = mapped_column(String(32), default=Role.MEMBER.value)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    group: Mapped[RoleGroup] = relationship(back_populates="mappings", lazy="selectin")


class RoleGroupMembership(Base):
    """A user's membership of a (custom) role group.

    Rows are recomputed at every login from the team mappings; ``source`` records
    how the membership was granted. The built-in moderator group is *not* stored
    here — moderator status is derived from the user's VoidSwitch role.
    """

    __tablename__ = "role_group_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "role_group_id", name="uq_user_group"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role_group_id: Mapped[int] = mapped_column(
        ForeignKey("role_groups.id", ondelete="CASCADE"), index=True
    )
    # How the membership was granted: "auto" (a team mapping matched) or
    # "manual" (assigned by a moderator from the dashboard). Auto memberships are
    # re-evaluated on every login; manual ones persist until removed.
    source: Mapped[str] = mapped_column(String(16), default="auto")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="group_memberships", lazy="selectin")
    group: Mapped[RoleGroup] = relationship(back_populates="memberships", lazy="selectin")


class Announcement(Base, TimestampMixin):
    """A platform announcement, shown in a login popup and on the dashboard.

    Published by staff (owner / co-owner / admin). The author's display name and
    role are snapshotted so the card can attribute it and so deletion/edit
    permission can be evaluated by tier (a user may always manage their own
    announcement, and may manage those authored by a *lower* tier). Edit history
    — including the previous and new title/body — is kept in the audit trail with
    the content stored as an owner-revealable secret, like other secrets.
    """

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    # Author snapshot (id + display name + role at publish time). ``created_by``
    # may be null if the author was later deleted; the name/role snapshots stay.
    created_by: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), default=None)
    created_by_role: Mapped[str] = mapped_column(String(32), default=Role.MEMBER.value)
    # Set once the announcement has been edited at least once (for an "edited" tag).
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    # Role group ids this announcement targets. Empty = everyone.
    target_role_group_ids: Mapped[list[int]] = mapped_column(JSON, default=list)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    # Composite (filter-column, id) indexes — see RequestLog.__table_args__.
    __table_args__ = (
        Index("ix_audit_logs_scope_id", "scope", "id"),
        Index("ix_audit_logs_action_id", "action", "id"),
        Index("ix_audit_logs_actor_sub_id", "actor_sub", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    actor_sub: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    actor_name: Mapped[str | None] = mapped_column(String(255), default=None)
    action: Mapped[str] = mapped_column(String(120), default="")
    # "admin" for management-surface actions, "self" for self-service ones
    # (sign-in/out, a user's own Void-Tokens). Lets the dashboard filter the
    # trail down to administrative actions only.
    scope: Mapped[str] = mapped_column(String(16), default="admin", index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), default=None)
    target_id: Mapped[str | None] = mapped_column(String(64), default=None)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    # Encrypted (Fernet) JSON blob with owner-only sensitive context, e.g. the
    # plaintext of keys added or the full details of a deleted key. Never exposed
    # to admins or members; revealed to owners on explicit, confirmed request.
    sensitive_ciphertext: Mapped[str | None] = mapped_column(Text, default=None)


class RequestLog(Base):
    __tablename__ = "request_logs"
    # Composite (filter-column, id) indexes backing the admin log browser's hot
    # query shape — ``WHERE <col> = ? ORDER BY id DESC LIMIT/OFFSET``. Declared
    # here so Alembic autogenerate treats them as part of the schema (they were
    # historically created by the frozen in-boot ``_ensure_indexes`` helper).
    __table_args__ = (
        Index("ix_request_logs_user_sub_id", "user_sub", "id"),
        Index("ix_request_logs_model_id", "model", "id"),
        Index("ix_request_logs_provider_name_id", "provider_name", "id"),
        Index("ix_request_logs_token_id_id", "token_id", "id"),
        Index("ix_request_logs_success_id", "success", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    # When the request was first received (= ts); kept separately for clarity.
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # When the response was fully delivered (non-stream) or the stream ended.
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Milliseconds from request receipt to first streamed token (TTFT).
    first_token_ms: Mapped[float | None] = mapped_column(Float, default=None)
    # Lifecycle status: "pending" (stream in flight), "completed", "cancelled", "error".
    req_status: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    # Client IP address (from X-Forwarded-For or request.client.host).
    client_ip: Mapped[str | None] = mapped_column(String(64), default=None)
    token_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    user_sub: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    # Stable identifier of the conversation/session behind the request (see
    # ``services.dispatcher._session_key``): a client-supplied session id, an
    # Anthropic ``metadata.user_id``, or a hash of the conversation prefix, always
    # namespaced by the calling token. Used to reconstruct per-session task spans
    # (the "longest task duration" statistic).
    session_id: Mapped[str | None] = mapped_column(String(255), default=None, index=True)
    provider_id: Mapped[int | None] = mapped_column(Integer, default=None)
    provider_name: Mapped[str | None] = mapped_column(String(120), default=None)
    key_id: Mapped[int | None] = mapped_column(Integer, default=None)
    proxy_id: Mapped[int | None] = mapped_column(Integer, default=None)
    model: Mapped[str | None] = mapped_column(String(120), default=None, index=True)
    # The upstream model the inbound ``model`` was routed to (alias route /
    # model_map). Equal to ``model`` when no routing applies. Non-sensitive, so
    # it is always recorded (not debug-gated) to trace model routing.
    upstream_model: Mapped[str | None] = mapped_column(String(120), default=None)
    inbound_style: Mapped[str | None] = mapped_column(String(32), default=None)
    upstream_style: Mapped[str | None] = mapped_column(String(32), default=None)
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)
    success: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, default=None)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    stream: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    # Client metadata
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    client_type: Mapped[str | None] = mapped_column(String(64), default=None)
    is_opencode: Mapped[bool] = mapped_column(Boolean, default=False)
    # Whether this row was recorded with debug-level detail (full req/resp).
    debug: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # HTTP method of the outbound upstream call (always POST today, recorded for
    # completeness/traceability). Non-sensitive.
    req_method: Mapped[str | None] = mapped_column(String(16), default=None)
    # Debug-only fields — populated only when the token has debug_enabled=True.
    req_headers: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    req_body: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    resp_headers: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # May be a JSON object, or a decoded text string for non-JSON upstream errors.
    resp_body: Mapped[Any | None] = mapped_column(JSON, default=None)
    # Per-attempt debug trail across the failover space (provider/key/proxy/route):
    # each entry has the outbound URL, method, proxy, redacted headers, body, the
    # upstream status, response headers/body, error class, and timing. This is what
    # makes an upstream 500 (or a total failover exhaustion) precisely diagnosable.
    debug_attempts: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    # Lightweight per-attempt summary, recorded for every request (not debug-gated)
    # so the detail modal can show each failover attempt's outcome.
    attempts_summary: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    upstream_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    proxy_url: Mapped[str | None] = mapped_column(String(512), default=None)


class UsageDaily(Base):
    """Per-user, per-day usage rollup that backs the activity heatmap.

    Incrementally upserted as requests complete (see ``services.usage_rollup``),
    independently of ``request_logs`` — so the heatmap, cumulative/peak token
    counts, and streaks survive request-log pruning and can be retained on their
    own, longer schedule (``heatmap_retention_days``, minimum one year). ``day``
    is the UTC calendar day (``YYYY-MM-DD``); ``user_sub`` is ``""`` for the rare
    request with no associated user. Site-wide figures are the sum across users.
    """

    __tablename__ = "usage_daily"
    __table_args__ = (
        UniqueConstraint("user_sub", "day", name="uq_usage_daily_user_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_sub: Mapped[str] = mapped_column(String(255), default="", index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (UTC)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class SessionSpan(Base):
    """The time span of one conversation/session, keyed by its session id.

    Upserted as requests complete: ``started_at`` is pinned to the first request
    of the session and ``last_at`` advances to the latest. The "longest task
    duration" statistic is ``max(last_at - started_at)`` over these rows (all
    sessions for a user, or every session for the site). Retained on the same
    ``heatmap_retention_days`` schedule as the daily rollup.
    """

    __tablename__ = "session_spans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    user_sub: Mapped[str] = mapped_column(String(255), default="", index=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    requests: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
