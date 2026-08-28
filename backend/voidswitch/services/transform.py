"""Bidirectional translation between the gateway's three API dialects.

The gateway speaks three styles — OpenAI **Chat Completions**, Anthropic
**Messages**, and OpenAI **Responses** — on both the inbound and the upstream
side. OpenAI Chat Completions is used as the *canonical hub*: every pair of
styles is converted by pivoting through it, so this module only defines the
direct conversions to/from that hub:

    openai <-> anthropic : request + response + stream
    openai <-> responses : request + response + stream

The dispatcher composes these (e.g. anthropic->responses = anthropic->openai then
openai->responses). Passthrough (matching styles) never touches this module.

Only the widely-used surface is translated faithfully: text, multi-part content,
tool/function calling, stop reasons, and token usage. Unknown fields are dropped
rather than passed through, to avoid leaking one vendor's params to the other.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

# --------------------------------------------------------------------------- #
# Stop-reason maps
# --------------------------------------------------------------------------- #

_ANTHROPIC_STOP_TO_OPENAI = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}
_OPENAI_FINISH_TO_ANTHROPIC = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "end_turn",
}

_DEFAULT_MAX_TOKENS = 4096

# Opaque placeholder attached to Anthropic "thinking" blocks reconstructed from an
# OpenAI upstream's ``reasoning_content``. Anthropic-dialect clients (e.g.
# @ai-sdk/anthropic, which OpenCode uses) only persist and *replay* a thinking block
# when it carries a signature; the gateway ignores the value when translating the
# block back to ``reasoning_content`` on the next turn. Without that round-trip,
# DeepSeek-style thinking upstreams reject the follow-up request with
# "The reasoning_content in the thinking mode must be passed back to the API.".
# The placeholder never reaches a real Anthropic upstream — only this gateway and the
# client see it — so a synthetic value is safe here.
_THINKING_SIGNATURE = "voidswitch"


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000):x}"


# --------------------------------------------------------------------------- #
# Request: OpenAI -> Anthropic
# --------------------------------------------------------------------------- #


def _openai_content_to_anthropic(content: Any) -> list[dict[str, Any]] | str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            blocks.append({"type": "text", "text": part.get("text", "")})
        elif ptype == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if url.startswith("data:") and ";base64," in url:
                media_type, b64 = url.split(";base64,", 1)
                media_type = media_type.removeprefix("data:")
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type or "image/png",
                            "data": b64,
                        },
                    }
                )
            elif url:
                blocks.append({"type": "image", "source": {"type": "url", "url": url}})
    return blocks or ""


def openai_request_to_anthropic(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "model": payload.get("model"),
        "max_tokens": payload.get("max_tokens")
        or payload.get("max_completion_tokens")
        or _DEFAULT_MAX_TOKENS,
    }
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []

    for msg in payload.get("messages", []):
        role = msg.get("role")
        if role == "system" or role == "developer":
            content = msg.get("content")
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                system_parts.extend(p.get("text", "") for p in content if isinstance(p, dict))
            continue
        if role == "tool":
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": _stringify(msg.get("content")),
                        }
                    ],
                }
            )
            continue
        if role == "assistant" and msg.get("tool_calls"):
            # Note: an assistant's reasoning_content is intentionally NOT replayed as a
            # thinking block toward an Anthropic upstream — real Anthropic rejects
            # thinking blocks without its own cryptographic signature, which a plain
            # OpenAI client cannot supply.
            blocks: list[dict[str, Any]] = []
            text = msg.get("content")
            if isinstance(text, str) and text:
                blocks.append({"type": "text", "text": text})
            for call in msg["tool_calls"]:
                fn = call.get("function", {})
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id", _gen_id("toolu")),
                        "name": fn.get("name", ""),
                        "input": _safe_json(fn.get("arguments")),
                    }
                )
            messages.append({"role": "assistant", "content": blocks})
            continue
        messages.append({"role": role, "content": _openai_content_to_anthropic(msg.get("content"))})

    if system_parts:
        out["system"] = "\n\n".join(p for p in system_parts if p)
    out["messages"] = messages

    for src, dst in (("temperature", "temperature"), ("top_p", "top_p")):
        if payload.get(src) is not None:
            out[dst] = payload[src]
    stop = payload.get("stop")
    if stop is not None:
        out["stop_sequences"] = [stop] if isinstance(stop, str) else stop
    if payload.get("stream"):
        out["stream"] = True
    if payload.get("tools"):
        out["tools"] = [_openai_tool_to_anthropic(t) for t in payload["tools"]]
    tool_choice = payload.get("tool_choice")
    if tool_choice is not None:
        out["tool_choice"] = _openai_tool_choice_to_anthropic(tool_choice)
    return out


def _openai_tool_to_anthropic(tool: dict[str, Any]) -> dict[str, Any]:
    fn = tool.get("function", tool)
    return {
        "name": fn.get("name", ""),
        "description": fn.get("description", ""),
        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
    }


def _openai_tool_choice_to_anthropic(choice: Any) -> dict[str, Any]:
    if choice == "auto":
        return {"type": "auto"}
    if choice == "required" or choice == "any":
        return {"type": "any"}
    if choice == "none":
        return {"type": "auto"}
    if isinstance(choice, dict) and choice.get("type") == "function":
        return {"type": "tool", "name": choice.get("function", {}).get("name", "")}
    return {"type": "auto"}


# --------------------------------------------------------------------------- #
# Request: Anthropic -> OpenAI
# --------------------------------------------------------------------------- #


def anthropic_request_to_openai(payload: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system = payload.get("system")
    if isinstance(system, str) and system:
        messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        text = "\n\n".join(p.get("text", "") for p in system if isinstance(p, dict))
        if text:
            messages.append({"role": "system", "content": text})

    for msg in payload.get("messages", []):
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue
        tool_calls: list[dict[str, Any]] = []
        text_parts: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        reasoning_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append({"type": "text", "text": block.get("text", "")})
            elif btype in ("thinking", "redacted_thinking"):
                # Carry prior reasoning back to thinking-mode upstreams (DeepSeek et al.),
                # which require the assistant turn's reasoning_content to be replayed.
                thinking_text = block.get("thinking") or ""
                if thinking_text:
                    reasoning_parts.append(thinking_text)
            elif btype == "image":
                src = block.get("source", {})
                if src.get("type") == "base64":
                    media = src.get("media_type", "image/png")
                    data_url = f"data:{media};base64,{src.get('data', '')}"
                else:
                    data_url = src.get("url", "")
                text_parts.append({"type": "image_url", "image_url": {"url": data_url}})
            elif btype == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id", _gen_id("call")),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    }
                )
            elif btype == "tool_result":
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": _stringify(block.get("content")),
                    }
                )

        reasoning_text = "".join(reasoning_parts)
        if role == "assistant" and tool_calls:
            text = "".join(p["text"] for p in text_parts if p.get("type") == "text")
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": text or None,
                "tool_calls": tool_calls,
            }
            if reasoning_text:
                assistant_msg["reasoning_content"] = reasoning_text
            messages.append(assistant_msg)
        elif tool_results:
            messages.extend(tool_results)
            leftover = [p for p in text_parts if p.get("type") != "image_url"]
            if leftover and any(p.get("type") == "text" and p["text"] for p in leftover):
                messages.append({"role": role, "content": leftover})
        else:
            simple = _collapse_openai_content(text_parts)
            simple_msg: dict[str, Any] = {"role": role, "content": simple}
            if role == "assistant" and reasoning_text:
                simple_msg["reasoning_content"] = reasoning_text
            messages.append(simple_msg)

    out: dict[str, Any] = {"model": payload.get("model"), "messages": messages}
    if payload.get("max_tokens"):
        out["max_tokens"] = payload["max_tokens"]
    for key in ("temperature", "top_p"):
        if payload.get(key) is not None:
            out[key] = payload[key]
    if payload.get("stop_sequences"):
        out["stop"] = payload["stop_sequences"]
    if payload.get("stream"):
        out["stream"] = True
    if payload.get("tools"):
        out["tools"] = [_anthropic_tool_to_openai(t) for t in payload["tools"]]
    tc = payload.get("tool_choice")
    if tc is not None:
        out["tool_choice"] = _anthropic_tool_choice_to_openai(tc)
    return out


def _collapse_openai_content(parts: list[dict[str, Any]]) -> Any:
    if not parts:
        return ""
    if len(parts) == 1 and parts[0].get("type") == "text":
        return parts[0]["text"]
    if all(p.get("type") == "text" for p in parts):
        return "".join(p["text"] for p in parts)
    return parts


def _anthropic_tool_to_openai(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def _anthropic_tool_choice_to_openai(choice: Any) -> Any:
    if not isinstance(choice, dict):
        return "auto"
    ctype = choice.get("type")
    if ctype == "auto":
        return "auto"
    if ctype == "any":
        return "required"
    if ctype == "tool":
        return {"type": "function", "function": {"name": choice.get("name", "")}}
    return "auto"


# --------------------------------------------------------------------------- #
# Non-streaming responses
# --------------------------------------------------------------------------- #


def anthropic_response_to_openai(resp: dict[str, Any], *, model: str) -> dict[str, Any]:
    content_text = ""
    reasoning_text = ""
    tool_calls: list[dict[str, Any]] = []
    for block in resp.get("content", []):
        if block.get("type") == "text":
            content_text += block.get("text", "")
        elif block.get("type") == "thinking":
            reasoning_text += block.get("thinking", "")
        elif block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id", _gen_id("call")),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                }
            )
    message: dict[str, Any] = {"role": "assistant", "content": content_text or None}
    if reasoning_text:
        message["reasoning_content"] = reasoning_text
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = resp.get("usage", {})
    prompt = usage.get("input_tokens", 0)
    completion = usage.get("output_tokens", 0)
    return {
        "id": resp.get("id", _gen_id("chatcmpl")),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": resp.get("model", model),
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": _ANTHROPIC_STOP_TO_OPENAI.get(resp.get("stop_reason", ""), "stop"),
            }
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


def openai_response_to_anthropic(resp: dict[str, Any], *, model: str) -> dict[str, Any]:
    choice = (resp.get("choices") or [{}])[0]
    message = choice.get("message", {})
    blocks: list[dict[str, Any]] = []
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        # Thinking blocks must precede text/tool_use; sign it so the client replays it.
        blocks.append({"type": "thinking", "thinking": reasoning, "signature": _THINKING_SIGNATURE})
    text = message.get("content")
    if isinstance(text, str) and text:
        blocks.append({"type": "text", "text": text})
    elif isinstance(text, list):
        for p in text:
            if isinstance(p, dict) and p.get("type") == "text":
                blocks.append({"type": "text", "text": p.get("text", "")})
    for call in message.get("tool_calls") or []:
        fn = call.get("function", {})
        blocks.append(
            {
                "type": "tool_use",
                "id": call.get("id", _gen_id("toolu")),
                "name": fn.get("name", ""),
                "input": _safe_json(fn.get("arguments")),
            }
        )
    usage = resp.get("usage", {})
    return {
        "id": resp.get("id", _gen_id("msg")),
        "type": "message",
        "role": "assistant",
        "model": resp.get("model", model),
        "content": blocks or [{"type": "text", "text": ""}],
        "stop_reason": _OPENAI_FINISH_TO_ANTHROPIC.get(
            choice.get("finish_reason") or "stop", "end_turn"
        ),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


# --------------------------------------------------------------------------- #
# SSE parsing
# --------------------------------------------------------------------------- #


async def iter_sse(stream: AsyncIterator[bytes]) -> AsyncIterator[tuple[str | None, str]]:
    """Yield ``(event, data)`` pairs from an SSE byte stream.

    CRLF line endings (legal per the SSE spec) are normalised to LF so frame
    splitting on ``\\n\\n`` works for both line styles.
    """
    buffer = ""
    async for chunk in stream:
        buffer += chunk.decode("utf-8", errors="replace").replace("\r\n", "\n")
        while "\n\n" in buffer:
            raw, buffer = buffer.split("\n\n", 1)
            event: str | None = None
            data_lines: list[str] = []
            for line in raw.splitlines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            if data_lines:
                yield event, "\n".join(data_lines)


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _data(data: dict[str, Any] | str) -> bytes:
    if isinstance(data, str):
        return f"data: {data}\n\n".encode()
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


# --------------------------------------------------------------------------- #
# Streaming: Anthropic upstream -> OpenAI client
# --------------------------------------------------------------------------- #


async def anthropic_stream_to_openai(
    stream: AsyncIterator[bytes], *, model: str
) -> AsyncIterator[bytes]:
    completion_id = _gen_id("chatcmpl")
    created = int(time.time())
    base = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
    }
    started = False
    block_types: dict[int, str] = {}
    tool_indexes: dict[int, int] = {}
    next_tool_index = 0

    async for event, data in iter_sse(stream):
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        etype = event or payload.get("type")

        if etype == "message_start":
            started = True
            yield _data(
                {
                    **base,
                    "choices": [
                        {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                    ],
                }
            )
        elif etype == "content_block_start":
            idx = payload.get("index", 0)
            block = payload.get("content_block", {})
            block_types[idx] = block.get("type", "text")
            if block.get("type") == "tool_use":
                tool_indexes[idx] = next_tool_index
                yield _data(
                    {
                        **base,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": next_tool_index,
                                            "id": block.get("id", ""),
                                            "type": "function",
                                            "function": {
                                                "name": block.get("name", ""),
                                                "arguments": "",
                                            },
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ],
                    }
                )
                next_tool_index += 1
        elif etype == "content_block_delta":
            idx = payload.get("index", 0)
            delta = payload.get("delta", {})
            if delta.get("type") == "text_delta":
                yield _data(
                    {
                        **base,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": delta.get("text", "")},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
            elif delta.get("type") == "thinking_delta":
                yield _data(
                    {
                        **base,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"reasoning_content": delta.get("thinking", "")},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
            elif delta.get("type") == "input_json_delta":
                tidx = tool_indexes.get(idx, 0)
                yield _data(
                    {
                        **base,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": tidx,
                                            "function": {
                                                "arguments": delta.get("partial_json", "")
                                            },
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ],
                    }
                )
        elif etype == "message_delta":
            stop = payload.get("delta", {}).get("stop_reason")
            finish = _ANTHROPIC_STOP_TO_OPENAI.get(stop or "", "stop")
            usage = payload.get("usage") or {}
            chunk: dict[str, Any] = {
                **base,
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            }
            if usage:
                chunk["usage"] = {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                }
            yield _data(chunk)
        elif etype == "message_stop":
            break

    if not started:
        yield _data(
            {
                **base,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": "stop",
                    }
                ],
            }
        )
    yield b"data: [DONE]\n\n"


# --------------------------------------------------------------------------- #
# Streaming: OpenAI upstream -> Anthropic client
# --------------------------------------------------------------------------- #


async def openai_stream_to_anthropic(
    stream: AsyncIterator[bytes], *, model: str
) -> AsyncIterator[bytes]:
    msg_id = _gen_id("msg")
    yield _sse(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )
    yield _sse("ping", {"type": "ping"})

    text_block_open = False
    text_index = 0
    thinking_block_open = False
    thinking_index = 0
    tool_blocks: dict[int, int] = {}  # openai tool index -> anthropic block index
    next_block = 0
    finish_reason = "stop"
    usage_out = {"input_tokens": 0, "output_tokens": 0}

    def _close_thinking() -> list[bytes]:
        # Seal the thinking block with a signature_delta so anthropic-dialect clients
        # persist and replay it — the round-trip thinking-mode upstreams require.
        return [
            _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": thinking_index,
                    "delta": {"type": "signature_delta", "signature": _THINKING_SIGNATURE},
                },
            ),
            _sse("content_block_stop", {"type": "content_block_stop", "index": thinking_index}),
        ]

    async for _event, data in iter_sse(stream):
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        if chunk.get("usage"):
            usage_out = {
                "input_tokens": chunk["usage"].get("prompt_tokens", 0),
                "output_tokens": chunk["usage"].get("completion_tokens", 0),
            }
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta", {})
        reasoning = delta.get("reasoning_content")
        if reasoning:
            # reasoning_content always streams before content/tool_calls — open a
            # leading thinking block (index 0) the first time we see it.
            if not thinking_block_open and not text_block_open and not tool_blocks:
                yield _sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": next_block,
                        "content_block": {"type": "thinking", "thinking": ""},
                    },
                )
                thinking_block_open = True
                thinking_index = next_block
                next_block += 1
            if thinking_block_open:
                yield _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": thinking_index,
                        "delta": {"type": "thinking_delta", "thinking": reasoning},
                    },
                )
        if delta.get("content"):
            if thinking_block_open:
                for _b in _close_thinking():
                    yield _b
                thinking_block_open = False
            if not text_block_open:
                yield _sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": next_block,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
                text_block_open = True
                text_index = next_block
                next_block += 1
            yield _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": text_index,
                    "delta": {"type": "text_delta", "text": delta["content"]},
                },
            )
        for call in delta.get("tool_calls") or []:
            oai_idx = call.get("index", 0)
            if oai_idx not in tool_blocks:
                if thinking_block_open:
                    for _b in _close_thinking():
                        yield _b
                    thinking_block_open = False
                if text_block_open:
                    yield _sse(
                        "content_block_stop", {"type": "content_block_stop", "index": text_index}
                    )
                    text_block_open = False
                tool_blocks[oai_idx] = next_block
                fn = call.get("function", {})
                yield _sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": next_block,
                        "content_block": {
                            "type": "tool_use",
                            "id": call.get("id", _gen_id("toolu")),
                            "name": fn.get("name", ""),
                            "input": {},
                        },
                    },
                )
                next_block += 1
            args = (call.get("function") or {}).get("arguments")
            if args:
                yield _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": tool_blocks[oai_idx],
                        "delta": {"type": "input_json_delta", "partial_json": args},
                    },
                )
        if choice.get("finish_reason"):
            finish_reason = _OPENAI_FINISH_TO_ANTHROPIC.get(choice["finish_reason"], "end_turn")

    if thinking_block_open:
        for _b in _close_thinking():
            yield _b
    if text_block_open:
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_index})
    for block_index in tool_blocks.values():
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
    yield _sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": finish_reason, "stop_sequence": None},
            "usage": usage_out,
        },
    )
    yield _sse("message_stop", {"type": "message_stop"})


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _stringify(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for part in content:
            if isinstance(part, dict):
                out.append(part.get("text", "") if part.get("type") == "text" else "")
            else:
                out.append(str(part))
        return "".join(out)
    return str(content)


def _safe_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {}
    return {}


def _openai_text(content: Any) -> str:
    """Flatten OpenAI message content (str or parts list) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return str(content)


# =========================================================================== #
# OpenAI Chat Completions  <->  OpenAI Responses
#
# Responses request shape:  {model, instructions, input:[items], max_output_tokens,
#   temperature, top_p, stream, tools:[{type:"function", name, ...}], tool_choice}
#   where an ``input`` item is one of:
#     {type:"message", role, content:[{type:"input_text"|"output_text", text}|
#                                      {type:"input_image", image_url}]}
#     {type:"function_call", call_id, name, arguments}
#     {type:"function_call_output", call_id, output}
# Responses response shape: {id, object:"response", status, output:[items], usage:
#   {input_tokens, output_tokens, total_tokens}} with a reasoning/message/function_call
#   item list mirroring the input items.
# =========================================================================== #

_OPENAI_FINISH_TO_RESP_STATUS = {
    "length": "incomplete",
    "content_filter": "incomplete",
}


# --------------------------------------------------------------------------- #
# Request: OpenAI -> Responses
# --------------------------------------------------------------------------- #


def _openai_content_to_responses(content: Any, *, assistant: bool) -> list[dict[str, Any]]:
    text_type = "output_text" if assistant else "input_text"
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": text_type, "text": content}] if content else []
    parts: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            parts.append({"type": text_type, "text": part.get("text", "")})
        elif ptype == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if url:
                parts.append({"type": "input_image", "image_url": url})
    return parts


def openai_request_to_responses(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"model": payload.get("model")}
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []

    for msg in payload.get("messages", []):
        role = msg.get("role")
        content = msg.get("content")
        if role in ("system", "developer"):
            text = _openai_text(content)
            if text:
                instructions.append(text)
            continue
        if role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": _stringify(content),
                }
            )
            continue
        if role == "assistant":
            text = _openai_text(content)
            if text:
                input_items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text}],
                    }
                )
            for call in msg.get("tool_calls") or []:
                fn = call.get("function", {})
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": call.get("id", _gen_id("call")),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments") or "{}",
                    }
                )
            continue
        # user (or any other) role.
        input_items.append(
            {
                "type": "message",
                "role": role,
                "content": _openai_content_to_responses(content, assistant=False),
            }
        )

    if instructions:
        out["instructions"] = "\n\n".join(instructions)
    out["input"] = input_items

    max_out = (
        payload.get("max_output_tokens")
        or payload.get("max_tokens")
        or payload.get("max_completion_tokens")
    )
    if max_out:
        out["max_output_tokens"] = max_out
    for key in ("temperature", "top_p"):
        if payload.get(key) is not None:
            out[key] = payload[key]
    if payload.get("stream"):
        out["stream"] = True
    if payload.get("tools"):
        out["tools"] = [_openai_tool_to_responses(t) for t in payload["tools"]]
    tool_choice = payload.get("tool_choice")
    if tool_choice is not None:
        out["tool_choice"] = _openai_tool_choice_to_responses(tool_choice)
    return out


def _openai_tool_to_responses(tool: dict[str, Any]) -> dict[str, Any]:
    fn = tool.get("function", tool)
    return {
        "type": "function",
        "name": fn.get("name", ""),
        "description": fn.get("description", ""),
        "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
    }


def _openai_tool_choice_to_responses(choice: Any) -> Any:
    if isinstance(choice, str):
        # "auto" / "none" / "required" carry over verbatim.
        return choice
    if isinstance(choice, dict) and choice.get("type") == "function":
        return {"type": "function", "name": choice.get("function", {}).get("name", "")}
    return "auto"


# --------------------------------------------------------------------------- #
# Request: Responses -> OpenAI
# --------------------------------------------------------------------------- #


def _responses_content_to_openai(content: Any) -> Any:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype in ("input_text", "output_text", "text"):
            parts.append({"type": "text", "text": part.get("text", "")})
        elif ptype == "input_image":
            url = part.get("image_url")
            if isinstance(url, dict):
                url = url.get("url", "")
            if url:
                parts.append({"type": "image_url", "image_url": {"url": url}})
    return _collapse_openai_content(parts)


def responses_request_to_openai(payload: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    instructions = payload.get("instructions")
    if isinstance(instructions, str) and instructions:
        messages.append({"role": "system", "content": instructions})

    raw_input = payload.get("input")
    if isinstance(raw_input, str):
        messages.append({"role": "user", "content": raw_input})
    elif isinstance(raw_input, list):
        for item in raw_input:
            if not isinstance(item, dict):
                continue
            itype = item.get("type", "message")
            if itype == "message":
                messages.append(
                    {
                        "role": item.get("role", "user"),
                        "content": _responses_content_to_openai(item.get("content")),
                    }
                )
            elif itype == "function_call":
                call = {
                    "id": item.get("call_id") or item.get("id", _gen_id("call")),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments") or "{}",
                    },
                }
                # Fold consecutive function calls into one assistant turn.
                if (
                    messages
                    and messages[-1].get("role") == "assistant"
                    and messages[-1].get("tool_calls")
                ):
                    messages[-1]["tool_calls"].append(call)
                else:
                    messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
            elif itype == "function_call_output":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.get("call_id", ""),
                        "content": _stringify(item.get("output")),
                    }
                )

    out: dict[str, Any] = {"model": payload.get("model"), "messages": messages}
    if payload.get("max_output_tokens"):
        out["max_tokens"] = payload["max_output_tokens"]
    for key in ("temperature", "top_p"):
        if payload.get(key) is not None:
            out[key] = payload[key]
    if payload.get("stream"):
        out["stream"] = True
    if payload.get("tools"):
        tools = [
            _responses_tool_to_openai(t)
            for t in payload["tools"]
            if isinstance(t, dict) and t.get("type") == "function"
        ]
        if tools:
            out["tools"] = tools
    tool_choice = payload.get("tool_choice")
    if tool_choice is not None:
        out["tool_choice"] = _responses_tool_choice_to_openai(tool_choice)
    return out


def _responses_tool_to_openai(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
        },
    }


def _responses_tool_choice_to_openai(choice: Any) -> Any:
    if isinstance(choice, str):
        return choice
    if isinstance(choice, dict) and choice.get("type") == "function":
        return {"type": "function", "function": {"name": choice.get("name", "")}}
    return "auto"


# --------------------------------------------------------------------------- #
# Non-streaming responses
# --------------------------------------------------------------------------- #


def openai_response_to_responses(resp: dict[str, Any], *, model: str) -> dict[str, Any]:
    choice = (resp.get("choices") or [{}])[0]
    message = choice.get("message", {})
    output: list[dict[str, Any]] = []

    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        output.append(
            {
                "type": "reasoning",
                "id": _gen_id("rs"),
                "summary": [{"type": "summary_text", "text": reasoning}],
            }
        )
    text = _openai_text(message.get("content"))
    if text:
        output.append(
            {
                "type": "message",
                "id": _gen_id("msg"),
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )
    for call in message.get("tool_calls") or []:
        fn = call.get("function", {})
        output.append(
            {
                "type": "function_call",
                "id": _gen_id("fc"),
                "call_id": call.get("id", _gen_id("call")),
                "name": fn.get("name", ""),
                "arguments": fn.get("arguments") or "{}",
                "status": "completed",
            }
        )

    usage = resp.get("usage", {})
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    finish = choice.get("finish_reason") or "stop"
    status = _OPENAI_FINISH_TO_RESP_STATUS.get(finish, "completed")
    out: dict[str, Any] = {
        "id": resp.get("id", _gen_id("resp")),
        "object": "response",
        "created_at": resp.get("created", int(time.time())),
        "model": resp.get("model", model),
        "status": status,
        "output": output,
        "output_text": text,
        "usage": {
            "input_tokens": prompt,
            "output_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }
    if status == "incomplete":
        reason = "max_output_tokens" if finish == "length" else "content_filter"
        out["incomplete_details"] = {"reason": reason}
    return out


def responses_response_to_openai(resp: dict[str, Any], *, model: str) -> dict[str, Any]:
    content_text = ""
    reasoning_text = ""
    tool_calls: list[dict[str, Any]] = []
    for item in resp.get("output", []):
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        if itype == "message":
            for part in item.get("content", []):
                if isinstance(part, dict) and part.get("type") in ("output_text", "text"):
                    content_text += part.get("text", "")
        elif itype == "reasoning":
            for part in item.get("summary", []):
                if isinstance(part, dict):
                    reasoning_text += part.get("text", "")
        elif itype == "function_call":
            tool_calls.append(
                {
                    "id": item.get("call_id") or item.get("id", _gen_id("call")),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments") or "{}",
                    },
                }
            )
    if not content_text and isinstance(resp.get("output_text"), str):
        content_text = resp["output_text"]

    message: dict[str, Any] = {"role": "assistant", "content": content_text or None}
    if reasoning_text:
        message["reasoning_content"] = reasoning_text
    if tool_calls:
        message["tool_calls"] = tool_calls

    finish = "tool_calls" if tool_calls else "stop"
    if resp.get("status") == "incomplete":
        reason = (resp.get("incomplete_details") or {}).get("reason")
        finish = "length" if reason == "max_output_tokens" else "content_filter"

    usage = resp.get("usage", {})
    prompt = usage.get("input_tokens", 0)
    completion = usage.get("output_tokens", 0)
    return {
        "id": resp.get("id", _gen_id("chatcmpl")),
        "object": "chat.completion",
        "created": int(resp.get("created_at") or time.time()),
        "model": resp.get("model", model),
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }


# --------------------------------------------------------------------------- #
# Streaming: OpenAI upstream -> Responses client
# --------------------------------------------------------------------------- #


async def openai_stream_to_responses(
    stream: AsyncIterator[bytes], *, model: str
) -> AsyncIterator[bytes]:
    """Translate an OpenAI chat.completion.chunk SSE stream into Responses events."""
    resp_id = _gen_id("resp")
    created = int(time.time())
    seq = 0

    def _next_seq() -> int:
        nonlocal seq
        n = seq
        seq += 1
        return n

    def _base_response(status: str, output: list[dict[str, Any]], usage: dict[str, int] | None):
        obj: dict[str, Any] = {
            "id": resp_id,
            "object": "response",
            "created_at": created,
            "model": model,
            "status": status,
            "output": output,
        }
        if usage is not None:
            obj["usage"] = usage
        return obj

    yield _sse(
        "response.created",
        {
            "type": "response.created",
            "sequence_number": _next_seq(),
            "response": _base_response("in_progress", [], None),
        },
    )

    output_index = 0
    text_item_id: str | None = None
    text_buffer = ""
    # openai tool index -> {output_index, item_id, name, call_id, args}
    tools: dict[int, dict[str, Any]] = {}
    finish_reason = "stop"
    usage_out = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    final_output: list[dict[str, Any]] = []

    def _open_text() -> list[bytes]:
        nonlocal text_item_id, output_index
        text_item_id = _gen_id("msg")
        events = [
            _sse(
                "response.output_item.added",
                {
                    "type": "response.output_item.added",
                    "sequence_number": _next_seq(),
                    "output_index": output_index,
                    "item": {
                        "id": text_item_id,
                        "type": "message",
                        "status": "in_progress",
                        "role": "assistant",
                        "content": [],
                    },
                },
            ),
            _sse(
                "response.content_part.added",
                {
                    "type": "response.content_part.added",
                    "sequence_number": _next_seq(),
                    "item_id": text_item_id,
                    "output_index": output_index,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": "", "annotations": []},
                },
            ),
        ]
        return events

    def _close_text() -> list[bytes]:
        nonlocal output_index, text_buffer, text_item_id
        assert text_item_id is not None
        buffered = text_buffer
        item = {
            "id": text_item_id,
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": buffered, "annotations": []}],
        }
        final_output.append(item)
        events = [
            _sse(
                "response.output_text.done",
                {
                    "type": "response.output_text.done",
                    "sequence_number": _next_seq(),
                    "item_id": text_item_id,
                    "output_index": output_index,
                    "content_index": 0,
                    "text": buffered,
                },
            ),
            _sse(
                "response.content_part.done",
                {
                    "type": "response.content_part.done",
                    "sequence_number": _next_seq(),
                    "item_id": text_item_id,
                    "output_index": output_index,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": buffered, "annotations": []},
                },
            ),
            _sse(
                "response.output_item.done",
                {
                    "type": "response.output_item.done",
                    "sequence_number": _next_seq(),
                    "output_index": output_index,
                    "item": item,
                },
            ),
        ]
        output_index += 1
        # Reset so a later text phase after tool calls opens a fresh block instead
        # of re-appending this one's text.
        text_buffer = ""
        text_item_id = None
        return events

    async for _event, data in iter_sse(stream):
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        if chunk.get("usage"):
            prompt = chunk["usage"].get("prompt_tokens", 0)
            completion = chunk["usage"].get("completion_tokens", 0)
            usage_out = {
                "input_tokens": prompt,
                "output_tokens": completion,
                "total_tokens": prompt + completion,
            }
        choice = (chunk.get("choices") or [{}])[0]
        delta = choice.get("delta", {})

        text_delta = delta.get("content")
        if text_delta:
            if text_item_id is None:
                for ev in _open_text():
                    yield ev
            text_buffer += text_delta
            yield _sse(
                "response.output_text.delta",
                {
                    "type": "response.output_text.delta",
                    "sequence_number": _next_seq(),
                    "item_id": text_item_id,
                    "output_index": output_index,
                    "content_index": 0,
                    "delta": text_delta,
                },
            )

        for call in delta.get("tool_calls") or []:
            # Close any open text block before the first tool call.
            if text_item_id is not None and not tools:
                for ev in _close_text():
                    yield ev
                text_item_id = None
            oai_idx = call.get("index", 0)
            fn = call.get("function", {})
            if oai_idx not in tools:
                item_id = _gen_id("fc")
                tools[oai_idx] = {
                    "output_index": output_index,
                    "item_id": item_id,
                    "call_id": call.get("id", _gen_id("call")),
                    "name": fn.get("name", ""),
                    "args": "",
                }
                yield _sse(
                    "response.output_item.added",
                    {
                        "type": "response.output_item.added",
                        "sequence_number": _next_seq(),
                        "output_index": output_index,
                        "item": {
                            "id": item_id,
                            "type": "function_call",
                            "status": "in_progress",
                            "call_id": tools[oai_idx]["call_id"],
                            "name": tools[oai_idx]["name"],
                            "arguments": "",
                        },
                    },
                )
                output_index += 1
            entry = tools[oai_idx]
            if fn.get("name") and not entry["name"]:
                entry["name"] = fn["name"]
            args_delta = fn.get("arguments")
            if args_delta:
                entry["args"] += args_delta
                yield _sse(
                    "response.function_call_arguments.delta",
                    {
                        "type": "response.function_call_arguments.delta",
                        "sequence_number": _next_seq(),
                        "item_id": entry["item_id"],
                        "output_index": entry["output_index"],
                        "delta": args_delta,
                    },
                )

        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]

    # Seal any still-open text block.
    if text_item_id is not None:
        for ev in _close_text():
            yield ev

    # Finalise tool-call items in order.
    for oai_idx in sorted(tools):
        entry = tools[oai_idx]
        item = {
            "id": entry["item_id"],
            "type": "function_call",
            "status": "completed",
            "call_id": entry["call_id"],
            "name": entry["name"],
            "arguments": entry["args"] or "{}",
        }
        final_output.append(item)
        yield _sse(
            "response.function_call_arguments.done",
            {
                "type": "response.function_call_arguments.done",
                "sequence_number": _next_seq(),
                "item_id": entry["item_id"],
                "output_index": entry["output_index"],
                "arguments": entry["args"] or "{}",
            },
        )
        yield _sse(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "sequence_number": _next_seq(),
                "output_index": entry["output_index"],
                "item": item,
            },
        )

    status = "incomplete" if finish_reason in ("length", "content_filter") else "completed"
    completed_event = "response.incomplete" if status == "incomplete" else "response.completed"
    response_obj = _base_response(status, final_output, usage_out)
    if status == "incomplete":
        response_obj["incomplete_details"] = {
            "reason": "max_output_tokens" if finish_reason == "length" else "content_filter"
        }
    yield _sse(
        completed_event,
        {
            "type": completed_event,
            "sequence_number": _next_seq(),
            "response": response_obj,
        },
    )


# --------------------------------------------------------------------------- #
# Streaming: Responses upstream -> OpenAI client
# --------------------------------------------------------------------------- #


async def responses_stream_to_openai(
    stream: AsyncIterator[bytes], *, model: str
) -> AsyncIterator[bytes]:
    """Translate a Responses SSE event stream into OpenAI chat.completion.chunk SSE."""
    completion_id = _gen_id("chatcmpl")
    created = int(time.time())
    base = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
    }
    role_sent = False
    # Responses output_index of a function_call -> OpenAI tool_calls array index.
    tool_index: dict[int, int] = {}
    next_tool = 0
    finish_reason = "stop"
    saw_tool = False
    usage_chunk: dict[str, Any] | None = None

    def _emit_role() -> bytes:
        return _data(
            {
                **base,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
        )

    async for event, data in iter_sse(stream):
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        etype = event or payload.get("type")

        if etype in ("response.created", "response.in_progress"):
            if not role_sent:
                role_sent = True
                yield _emit_role()
            continue

        if etype == "response.output_item.added":
            item = payload.get("item", {})
            if item.get("type") == "function_call":
                if not role_sent:
                    role_sent = True
                    yield _emit_role()
                saw_tool = True
                out_idx = payload.get("output_index", 0)
                tool_index[out_idx] = next_tool
                yield _data(
                    {
                        **base,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": next_tool,
                                            "id": item.get("call_id", ""),
                                            "type": "function",
                                            "function": {
                                                "name": item.get("name", ""),
                                                "arguments": "",
                                            },
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ],
                    }
                )
                next_tool += 1
            continue

        if etype in ("response.output_text.delta", "response.refusal.delta"):
            if not role_sent:
                role_sent = True
                yield _emit_role()
            text = payload.get("delta", "")
            if isinstance(text, dict):
                text = text.get("text", "")
            if text:
                yield _data(
                    {
                        **base,
                        "choices": [
                            {"index": 0, "delta": {"content": text}, "finish_reason": None}
                        ],
                    }
                )
            continue

        if etype in (
            "response.reasoning_summary_text.delta",
            "response.reasoning_text.delta",
        ):
            if not role_sent:
                role_sent = True
                yield _emit_role()
            text = payload.get("delta", "")
            if isinstance(text, dict):
                text = text.get("text", "")
            if text:
                yield _data(
                    {
                        **base,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"reasoning_content": text},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
            continue

        if etype == "response.function_call_arguments.delta":
            out_idx = payload.get("output_index", 0)
            tidx = tool_index.get(out_idx, 0)
            args = payload.get("delta", "")
            if args:
                yield _data(
                    {
                        **base,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [{"index": tidx, "function": {"arguments": args}}]
                                },
                                "finish_reason": None,
                            }
                        ],
                    }
                )
            continue

        if etype in ("response.completed", "response.incomplete", "response.failed"):
            resp = payload.get("response", {})
            usage = resp.get("usage") or {}
            prompt = usage.get("input_tokens", 0)
            completion = usage.get("output_tokens", 0)
            usage_chunk = {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": usage.get("total_tokens", prompt + completion),
            }
            if resp.get("status") == "incomplete":
                reason = (resp.get("incomplete_details") or {}).get("reason")
                finish_reason = "length" if reason == "max_output_tokens" else "content_filter"
            elif saw_tool:
                finish_reason = "tool_calls"
            else:
                finish_reason = "stop"
            break

    if not role_sent:
        yield _emit_role()
    if saw_tool and finish_reason == "stop":
        finish_reason = "tool_calls"
    final_chunk: dict[str, Any] = {
        **base,
        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
    }
    if usage_chunk is not None:
        final_chunk["usage"] = usage_chunk
    yield _data(final_chunk)
    yield b"data: [DONE]\n\n"
