"""Claude Code subscription OAuth adapter."""

from __future__ import annotations

import hashlib
import platform
from typing import TYPE_CHECKING, Any

from voidswitch.services import oauth_tokens

from .anthropic import AnthropicProvider

if TYPE_CHECKING:
    from voidswitch.models.db import ApiKey


CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
OPENCODE_IDENTITY_LINE = "You are OpenCode, the best coding agent on the planet."
CLAUDE_CODE_VERSION = "2.1.158"
ANTHROPIC_SDK_VERSION = "0.94.0"
_DEFAULT_BETAS = ("claude-code-20250219", "oauth-2025-04-20")
_OPENCODE_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("https://github.com/anomalyco/opencode", "https://github.com/anthropics/claude-code"),
    ("https://opencode.ai/docs", "https://docs.claude.com/en/docs/claude-code"),
    ("https://opencode.ai", "https://docs.claude.com/en/docs/claude-code"),
    ("OpenCode", "Claude Code"),
    ("opencode", "claude-code"),
    ("voidswitch/", ""),
)


class ClaudeCodeProvider(AnthropicProvider):
    type = "claude-code"
    refresh_on_invalid_key = True
    supports_import = True
    supports_refresh = True

    async def resolve_credential(
        self,
        session: Any,
        key: ApiKey,
        secret_key: str,
        *,
        force_refresh: bool = False,
    ) -> str:
        return await oauth_tokens.resolve_access_token(
            session,
            key,
            secret_key=secret_key,
            force_refresh=force_refresh,
        )

    def headers(self, api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
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

        betas: list[str] = list(_DEFAULT_BETAS)
        for b in incoming.split(","):
            b = b.strip()
            if b and b not in betas:
                betas.append(b)

        base.update(merged)
        base["anthropic-beta"] = ",".join(dict.fromkeys(betas))
        return base

    def prepare_body(self, body: dict[str, Any]) -> dict[str, Any]:
        body = dict(body)
        drop_block = bool(self.record.drop_opencode_identity_block)
        system = _strip_opencode_identity(body.get("system"), drop_block=drop_block)
        blocks = _ensure_identity(system)
        blocks[0] = {**blocks[0], "cache_control": {"type": "ephemeral"}}
        body["system"] = blocks
        if isinstance(body.get("tools"), list):
            body["tools"] = _scrub_opencode_tree(body["tools"])
        _cap_cache_control(body, limit=4)
        return body

    def _session_id(self) -> str:
        digest = hashlib.sha256(f"{self.record.id}:{self.record.name}".encode()).hexdigest()
        return f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-8{digest[17:20]}-{digest[20:32]}"


def _stainless_os() -> str:
    return {
        "Darwin": "MacOS",
        "Windows": "Windows",
        "FreeBSD": "FreeBSD",
        "OpenBSD": "OpenBSD",
        "Linux": "Linux",
        "Java": "Unknown",
    }.get(platform.system(), f"Other:{platform.system()}" if platform.system() else "Unknown")


def _stainless_arch() -> str:
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


def _cap_cache_control(body: dict[str, Any], limit: int = 4) -> None:
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
    if OPENCODE_IDENTITY_LINE in text:
        kept = [ln for ln in text.split("\n") if ln.strip() != OPENCODE_IDENTITY_LINE]
        text = "\n".join(kept).lstrip("\n")
    return _apply_opencode_substitutions(text)


def _scrub_opencode_tree(obj: Any) -> Any:
    if isinstance(obj, str):
        return _apply_opencode_substitutions(obj)
    if isinstance(obj, list):
        return [_scrub_opencode_tree(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _scrub_opencode_tree(v) for k, v in obj.items()}
    return obj


def _strip_opencode_identity(system: Any, *, drop_block: bool = False) -> Any:
    if isinstance(system, str):
        if drop_block and OPENCODE_IDENTITY_LINE in system:
            return ""
        return _scrub_opencode_text(system)
    if isinstance(system, list):
        out: list[Any] = []
        for b in system:
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                if drop_block and OPENCODE_IDENTITY_LINE in b["text"]:
                    continue
                scrubbed = _scrub_opencode_text(b["text"])
                if not scrubbed.strip():
                    continue
                b = {**b, "text": scrubbed}
            out.append(b)
        return out
    return system


def _ensure_identity(system: Any) -> list[dict[str, Any]]:
    identity = {"type": "text", "text": CLAUDE_CODE_IDENTITY}
    if system is None or system == "":
        return [identity]
    if isinstance(system, str):
        blocks = [{"type": "text", "text": system}]
    elif isinstance(system, list):
        blocks = [b for b in system if isinstance(b, dict)]
    else:
        return [identity]
    first_text = blocks[0].get("text", "") if blocks else ""
    if first_text.strip().startswith(CLAUDE_CODE_IDENTITY):
        return blocks
    return [identity, *blocks]
