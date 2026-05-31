"""Bidirectional translation between OpenAI Chat Completions and Anthropic Messages.

The gateway accepts either inbound style and can forward to a provider speaking
either style, so we need all four conversions plus their streaming variants:

    inbound openai  -> upstream anthropic : request + response + stream
    inbound anthropic -> upstream openai  : request + response + stream

Passthrough (matching styles) never touches this module.

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
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append({"type": "text", "text": block.get("text", "")})
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

        if role == "assistant" and tool_calls:
            text = "".join(p["text"] for p in text_parts if p.get("type") == "text")
            messages.append(
                {"role": "assistant", "content": text or None, "tool_calls": tool_calls}
            )
        elif tool_results:
            messages.extend(tool_results)
            leftover = [p for p in text_parts if p.get("type") != "image_url" or True]
            if leftover and any(p.get("type") == "text" and p["text"] for p in leftover):
                messages.append({"role": role, "content": leftover})
        else:
            simple = _collapse_openai_content(text_parts)
            messages.append({"role": role, "content": simple})

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
    tool_calls: list[dict[str, Any]] = []
    for block in resp.get("content", []):
        if block.get("type") == "text":
            content_text += block.get("text", "")
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
    """Yield ``(event, data)`` pairs from an SSE byte stream."""
    buffer = ""
    async for chunk in stream:
        buffer += chunk.decode("utf-8", errors="replace")
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
    tool_blocks: dict[int, int] = {}  # openai tool index -> anthropic block index
    next_block = 0
    finish_reason = "stop"
    usage_out = {"input_tokens": 0, "output_tokens": 0}

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
        if delta.get("content"):
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
