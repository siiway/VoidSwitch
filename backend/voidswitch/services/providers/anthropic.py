"""Anthropic-style adapters.

Two flavours:

* :class:`AnthropicProvider` — standard paid API-key access (``x-api-key``).
* :class:`ClaudeCodeProvider` — the "reverse-engineered" Claude Code path: use a
  Claude **subscription** OAuth token (from ``claude setup-token``) as a Bearer
  credential. This requires the ``oauth-2025-04-20`` beta and that the request
  leads with the Claude Code identity system prompt, exactly as the CLI sends it.
"""

from __future__ import annotations

import hashlib
import platform
from typing import Any

from voidswitch.constants import ApiStyle

from .base import BaseProvider

# The exact identity string the Claude Code CLI sends as its first system block
# (``cli.js``: ``wY6``). OAuth/subscription inference is only authorised for Claude
# Code traffic, so the request must lead with this or the API rejects it.
CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."

# The exact self-identity line OpenCode (pointed here via ``ANTHROPIC_BASE_URL``)
# leads its system prompt with — ``prompt/{anthropic,codex}.txt`` line 1. It has no
# Claude Code analogue, so it's deleted outright rather than rewritten.
OPENCODE_IDENTITY_LINE = "You are OpenCode, the best coding agent on the planet."

# Beyond the identity line, OpenCode brands itself in many places — the system
# prompt's feedback/docs URLs, the "ask about OpenCode" guidance, the skills footer
# (``customize-opencode``, ``opencode.json``, ``~/.config/opencode``), and — across
# every tool definition — the ``…/Temp/opencode`` scratch path. The gateway also
# leaks through the model id OpenCode echoes ("voidswitch/claude-opus-4-8"). Any one
# of these tells Anthropic the traffic isn't the real Claude Code CLI, so every
# occurrence is rewritten to the Claude Code equivalent (which is what the genuine
# CLI actually sends). URL rewrites run before the bare-word ones because the URLs
# embed the lowercase brand token; ``voidswitch/`` is dropped so the model id reads
# plainly, as the real CLI sends it.
_OPENCODE_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    (
        "https://github.com/anomalyco/opencode",
        "https://github.com/anthropics/claude-code",
    ),
    ("https://opencode.ai/docs", "https://docs.claude.com/en/docs/claude-code"),
    ("https://opencode.ai", "https://docs.claude.com/en/docs/claude-code"),
    ("OpenCode", "Claude Code"),
    ("opencode", "claude-code"),
    ("voidswitch/", ""),
)

# Claude Code CLI version advertised in the user-agent (``cli.js``: ``VERSION``).
CLAUDE_CODE_VERSION = "2.1.158"

# Version of the bundled ``@anthropic-ai/sdk`` (``cli.js``: ``JF``). The SDK stamps
# this into ``x-stainless-package-version`` on every request.
ANTHROPIC_SDK_VERSION = "0.94.0"

# Betas the CLI always sends on a subscription request (``cli.js`` beta builder):
#   * `claude-code-20250219` (``oZH``) marks the traffic as Claude Code — required,
#     alongside the identity prefix, for subscription/OAuth inference to be
#     authorised, and pushed unconditionally;
#   * `oauth-2025-04-20` (``IBH``) enables the Bearer-OAuth credential.
# Every other beta the CLI sends (interleaved-thinking, context-1m,
# context-management, …) is request-conditional, so we union the two mandatory
# defaults with whatever betas the caller passes through — when the inbound client
# is a real Claude Code CLI, its exact computed beta set is preserved verbatim.
_DEFAULT_BETAS = ("claude-code-20250219", "oauth-2025-04-20")


def _stainless_os() -> str:
    """The host OS as the Anthropic TS SDK reports it (``cli.js``: ``h5q``)."""
    return {
        "Darwin": "MacOS",
        "Windows": "Windows",
        "FreeBSD": "FreeBSD",
        "OpenBSD": "OpenBSD",
        "Linux": "Linux",
        "Java": "Unknown",
    }.get(platform.system(), f"Other:{platform.system()}" if platform.system() else "Unknown")


def _stainless_arch() -> str:
    """The host arch as the Anthropic TS SDK reports it (``cli.js``: ``y5q``)."""
    machine = platform.machine().lower()
    if machine == "x32":
        return "x32"
    if machine in ("x86_64", "amd64", "x64"):
        return "x64"
    if machine == "arm":
        return "arm"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return f"other:{machine}" if machine else "unknown"


class AnthropicProvider(BaseProvider):
    type = "anthropic"
    style = ApiStyle.ANTHROPIC
    default_base_url = "https://api.anthropic.com"
    default_models = (
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    )
    messages_suffix = "/v1/messages"
    models_suffix = "/v1/models"


class ClaudeCodeProvider(AnthropicProvider):
    """Claude via a subscription OAuth token (Pro/Max), à la Claude Code.

    A key is either a long-lived token from ``claude setup-token`` or an OAuth
    credential bundle. The dashboard can mint a bundle directly via the
    subscription login (``POST /oauth/start`` → ``/oauth/complete``); bundles are
    auto-refreshed by :mod:`voidswitch.services.oauth_tokens`. Auth is always
    ``Authorization: Bearer <token>``.
    """

    type = "claude-code"

    def headers(self, api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        # The full header set the Claude Code CLI sends: Bearer OAuth, the CLI
        # user-agent + `x-app: cli`, and the Anthropic TS SDK's `x-stainless-*`
        # telemetry fingerprint. voidswitch originates the upstream request (the
        # inbound client's UA/SDK headers are not forwarded), so this is the whole
        # wire fingerprint.
        base: dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": f"claude-cli/{CLAUDE_CODE_VERSION} (external, cli)",
            "x-app": "cli",
            "x-claude-code-session-id": self._session_id(),
            "x-stainless-lang": "js",
            "x-stainless-package-version": ANTHROPIC_SDK_VERSION,
            "x-stainless-os": _stainless_os(),
            "x-stainless-arch": _stainless_arch(),
            "x-stainless-runtime": "node",
            "x-stainless-runtime-version": "v24.0.0",
            "x-stainless-retry-count": "0",
        }

        # Collect extra/passthrough headers, pulling out any incoming beta list so
        # we can union it with the default CLI betas (dropping oauth-2025-04-20
        # would break Bearer auth; dropping claude-code-20250219 would un-mark the
        # traffic as Claude Code).
        merged: dict[str, str] = {}
        if self.record.extra_headers:
            merged.update({str(k): str(v) for k, v in self.record.extra_headers.items()})
        if extra:
            merged.update(extra)

        incoming = ""
        for key in list(merged):
            if key.lower() == "anthropic-beta":
                incoming = merged.pop(key)
        merged.pop("x-api-key", None)
        merged.pop("Authorization", None)

        betas = list(_DEFAULT_BETAS)
        for b in incoming.split(","):
            b = b.strip()
            if b and b not in betas:
                betas.append(b)

        base.update(merged)
        base["anthropic-beta"] = ",".join(dict.fromkeys(betas))
        return base

    def prepare_body(self, body: dict[str, Any]) -> dict[str, Any]:
        body = dict(body)
        # Anti-detection: OpenCode brands itself throughout its system prompt
        # (identity line, feedback/docs URLs, the "ask about OpenCode" guidance,
        # the skills footer). Scrub every such fingerprint before injecting ours —
        # a real Claude Code request carries none of them; see
        # ``_strip_opencode_identity``. When the provider opts in, the whole
        # identity-bearing block is dropped rather than scrubbed in place.
        drop_block = bool(self.record.drop_opencode_identity_block)
        system = _strip_opencode_identity(body.get("system"), drop_block=drop_block)
        # Mirror Claude Code's system layout (utils/api.ts:splitSysPromptPrefix):
        #   [ identity prefix (cached), ...caller system content ]
        # The identity must lead, and is cached as a stable prompt prefix.
        blocks = _ensure_identity(system)
        blocks[0] = {**blocks[0], "cache_control": {"type": "ephemeral"}}
        body["system"] = blocks
        # The same fingerprints recur across every tool definition (the OpenCode
        # scratch path, the customize-opencode skill text), so scrub those too.
        if isinstance(body.get("tools"), list):
            body["tools"] = _scrub_opencode_tree(body["tools"])
        # Anthropic allows at most 4 ``cache_control`` breakpoints across the whole
        # request (tools + system + messages). A client such as Claude Code or
        # OpenCode may already use its full budget; prepending our identity
        # breakpoint then makes 5 and the API rejects the request with
        # "A maximum of 4 blocks with cache_control may be provided. Found 5."
        # Real Claude Code keeps itself under the cap (and strips overflow); we do
        # the same here so any well-behaved client survives the identity injection.
        _cap_cache_control(body, limit=4)
        return body

    def _session_id(self) -> str:
        """A stable, UUID-shaped session id, like the CLI's ``X-Claude-Code-Session-Id``.

        The real CLI mints a fresh v4 UUID per launch and reuses it for every
        request in that session. We derive one deterministically per provider so
        all of a provider's traffic shares one session id (and it survives a
        restart) without needing a RNG.
        """
        digest = hashlib.sha256(f"{self.record.id}:{self.record.name}".encode()).hexdigest()
        # Lay the hash out as a v4 UUID: set the version nibble (4) and variant.
        return f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-8{digest[17:20]}-{digest[20:32]}"


def _cap_cache_control(body: dict[str, Any], limit: int = 4) -> None:
    """Strip ``cache_control`` from the earliest blocks until at most ``limit`` remain.

    Anthropic counts cache_control breakpoints across tools, system, and message
    content (max 4). A breakpoint caches everything up to its block, so later
    breakpoints subsume earlier ones — dropping the earliest sheds the least cache
    value (our single-sentence identity prefix is the first to go). Mutates in
    place; the upstream body is the only consumer.
    """
    carriers: list[dict[str, Any]] = []

    tools = body.get("tools")
    if isinstance(tools, list):
        carriers += [t for t in tools if isinstance(t, dict) and "cache_control" in t]

    system = body.get("system")
    if isinstance(system, list):
        carriers += [b for b in system if isinstance(b, dict) and "cache_control" in b]

    messages = body.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                carriers += [b for b in content if isinstance(b, dict) and "cache_control" in b]

    excess = len(carriers) - limit
    if excess > 0:
        for block in carriers[:excess]:
            block.pop("cache_control", None)


def _apply_opencode_substitutions(text: str) -> str:
    for needle, replacement in _OPENCODE_SUBSTITUTIONS:
        text = text.replace(needle, replacement)
    return text


def _scrub_opencode_text(text: str) -> str:
    """Remove every OpenCode fingerprint from a block of system text.

    First the standalone identity line is deleted (and the blank line it leaves
    behind), then each residual brand/URL tell is rewritten to its Claude Code
    equivalent. Text with no fingerprints is returned unchanged.
    """
    if OPENCODE_IDENTITY_LINE in text:
        kept = [ln for ln in text.split("\n") if ln.strip() != OPENCODE_IDENTITY_LINE]
        text = "\n".join(kept).lstrip("\n")
    return _apply_opencode_substitutions(text)


def _scrub_opencode_tree(obj: Any) -> Any:
    """Recursively rewrite OpenCode brand/URL tells in every string of a structure.

    Used for the ``tools`` definitions, whose descriptions embed the OpenCode
    scratch path and the ``customize-opencode`` / ``opencode.json`` skills guidance.
    The shape (dict keys, list order) is preserved; only string *values* change, and
    only where a fingerprint matches — tool names carry none, so routing is intact.
    """
    if isinstance(obj, str):
        return _apply_opencode_substitutions(obj)
    if isinstance(obj, list):
        return [_scrub_opencode_tree(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _scrub_opencode_tree(v) for k, v in obj.items()}
    return obj


def _strip_opencode_identity(system: Any, *, drop_block: bool = False) -> Any:
    """Scrub OpenCode fingerprints from a system prompt, preserving its shape.

    ``system`` may be a plain string or Anthropic's block list. Every block's text
    is scrubbed; a block reduced to nothing (it held only the identity line) is
    dropped so no empty block is forwarded.

    When ``drop_block`` is set, any block that carries the OpenCode identity line is
    discarded wholesale instead of being scrubbed — the provider-level opt-in for
    sending only the injected Claude Code identity, with none of the caller's prompt.
    """
    if isinstance(system, str):
        if drop_block and OPENCODE_IDENTITY_LINE in system:
            return ""
        return _scrub_opencode_text(system)
    if isinstance(system, list):
        out: list[Any] = []
        for b in system:
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                if drop_block and OPENCODE_IDENTITY_LINE in b["text"]:
                    continue  # drop the entire identity-bearing block
                scrubbed = _scrub_opencode_text(b["text"])
                if not scrubbed.strip():
                    continue
                b = {**b, "text": scrubbed}
            out.append(b)
        return out
    return system


def _ensure_identity(system: Any) -> list[dict[str, Any]]:
    """Return a system block list whose first block is the Claude Code identity."""
    identity = {"type": "text", "text": CLAUDE_CODE_IDENTITY}

    if system is None or system == "":
        return [identity]

    blocks: list[dict[str, Any]]
    if isinstance(system, str):
        blocks = [{"type": "text", "text": system}]
    elif isinstance(system, list):
        blocks = [b for b in system if isinstance(b, dict)]
    else:
        blocks = [identity]
        return blocks

    first_text = blocks[0].get("text", "") if blocks else ""
    if first_text.strip().startswith(CLAUDE_CODE_IDENTITY):
        return blocks
    return [identity, *blocks]
