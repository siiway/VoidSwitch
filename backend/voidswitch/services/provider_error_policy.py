"""Pure relay-error attribution and selective-ignore policy evaluation."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any

MAX_MATCH_TEXT_BYTES = 64 * 1024
PROTECTED_ORIGIN_STATUSES = frozenset({401, 402, 403, 429})
_STATUS_PART = re.compile(r"^(\d{3})(?:\s*-\s*(\d{3}))?$")


class ErrorProvenance(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    RELAY = "relay"
    ORIGIN = "origin"
    UNKNOWN = "unknown"


class PolicyAction(StrEnum):
    USE_ADAPTER = "use_adapter"
    PROTECT = "protect"


@dataclass(frozen=True)
class RuleMatch:
    rule_name: str
    status_matched: bool
    body_matched: bool


@dataclass(frozen=True)
class ProviderErrorDecision:
    action: PolicyAction
    original_classification: str
    final_classification: str
    provenance: ErrorProvenance
    matched_rule_name: str | None = None
    status_matched: bool = False
    body_matched: bool = False

    @property
    def protected(self) -> bool:
        return self.action is PolicyAction.PROTECT


def normalize_status_expression(expression: str) -> str:
    """Validate an HTTP status expression and return merged canonical ranges."""
    expression = expression.strip()
    if not expression:
        raise ValueError("status expression must not be blank")

    ranges: list[tuple[int, int]] = []
    for raw_part in expression.split(","):
        part = raw_part.strip()
        match = _STATUS_PART.fullmatch(part)
        if match is None:
            raise ValueError(f"invalid status expression part: {raw_part!r}")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if not 100 <= start <= 599 or not 100 <= end <= 599:
            raise ValueError("status codes must be between 100 and 599")
        if start > end:
            raise ValueError("status range start must not exceed its end")
        ranges.append((start, end))

    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return ",".join(str(start) if start == end else f"{start}-{end}" for start, end in merged)


@lru_cache(maxsize=1024)
def _status_ranges(normalized_expression: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    for part in normalized_expression.split(","):
        start_raw, separator, end_raw = part.partition("-")
        start = int(start_raw)
        ranges.append((start, int(end_raw) if separator else start))
    return tuple(ranges)


def _rule_value(rule: object, name: str, default: Any = None) -> Any:
    if isinstance(rule, Mapping):
        return rule.get(name, default)
    return getattr(rule, name, default)


def _iter_json_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _iter_json_strings(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _iter_json_strings(child)


def _matching_text(body: object) -> str:
    value = body
    if isinstance(body, (bytes, bytearray)):
        raw = bytes(body).decode("utf-8", errors="replace")
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            value = raw
    elif isinstance(body, str):
        with suppress(json.JSONDecodeError, ValueError):
            value = json.loads(body)

    strings = _iter_json_strings(value)
    aggregate = bytearray()
    for text in strings:
        if aggregate:
            if len(aggregate) >= MAX_MATCH_TEXT_BYTES:
                break
            aggregate.extend(b"\n")
        remaining = MAX_MATCH_TEXT_BYTES - len(aggregate)
        if remaining <= 0:
            break
        aggregate.extend(text.encode("utf-8")[:remaining])
    return aggregate.decode("utf-8", errors="ignore").casefold()


def match_selective_ignore_rule(
    rules: Sequence[object], *, status_code: int, body: object
) -> RuleMatch | None:
    """Return the first enabled matching rule from an already validated rule list."""
    matching_text: str | None = None
    for rule in rules:
        if not bool(_rule_value(rule, "enabled", True)):
            continue
        status_expression = _rule_value(rule, "status_codes")
        substrings = _rule_value(rule, "body_substrings", []) or []
        status_matched = status_expression is None or any(
            start <= status_code <= end for start, end in _status_ranges(status_expression)
        )
        if not status_matched:
            continue
        body_matched = not substrings
        if substrings:
            if matching_text is None:
                matching_text = _matching_text(body)
            body_matched = any(str(item).casefold() in matching_text for item in substrings)
        if body_matched:
            return RuleMatch(
                rule_name=str(_rule_value(rule, "name")),
                status_matched=status_expression is not None,
                body_matched=bool(substrings),
            )
    return None


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if key.casefold() == target:
            return value
    return None


def _new_api_active(mode: str, headers: Mapping[str, str]) -> bool:
    if mode == "enabled":
        return True
    if mode == "disabled":
        return False
    value = _header_value(headers, "X-New-Api-Version")
    return isinstance(value, str) and bool(value.strip())


def _new_api_provenance(body: object) -> ErrorProvenance:
    if isinstance(body, (bytes, bytearray)):
        try:
            body = json.loads(bytes(body))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return ErrorProvenance.UNKNOWN
    elif isinstance(body, str):
        try:
            body = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return ErrorProvenance.UNKNOWN
    if not isinstance(body, Mapping):
        return ErrorProvenance.UNKNOWN
    error = body.get("error")
    if not isinstance(error, Mapping):
        return ErrorProvenance.UNKNOWN
    error_type = error.get("type")
    if not isinstance(error_type, str) or not error_type.strip():
        return ErrorProvenance.UNKNOWN
    if error_type == "new_api_error":
        return ErrorProvenance.RELAY
    return ErrorProvenance.ORIGIN


def evaluate_provider_error_policy(
    *,
    new_api_mode: str,
    selective_ignore_rules: Sequence[object],
    status_code: int,
    headers: Mapping[str, str],
    body: object,
    original_classification: str,
) -> ProviderErrorDecision:
    """Classify policy only; callers remain responsible for state and retries."""
    rule_match = match_selective_ignore_rule(
        selective_ignore_rules, status_code=status_code, body=body
    )
    if rule_match is not None:
        return ProviderErrorDecision(
            action=PolicyAction.PROTECT,
            original_classification=original_classification,
            final_classification="selective_ignore",
            provenance=ErrorProvenance.NOT_EVALUATED,
            matched_rule_name=rule_match.rule_name,
            status_matched=rule_match.status_matched,
            body_matched=rule_match.body_matched,
        )

    provenance = ErrorProvenance.NOT_EVALUATED
    if _new_api_active(new_api_mode, headers):
        provenance = _new_api_provenance(body)
        if provenance is ErrorProvenance.ORIGIN and status_code in PROTECTED_ORIGIN_STATUSES:
            return ProviderErrorDecision(
                action=PolicyAction.PROTECT,
                original_classification=original_classification,
                final_classification="protected_origin_error",
                provenance=provenance,
            )

    return ProviderErrorDecision(
        action=PolicyAction.USE_ADAPTER,
        original_classification=original_classification,
        final_classification=original_classification,
        provenance=provenance,
    )
