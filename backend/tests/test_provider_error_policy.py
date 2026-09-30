from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError
from voidswitch.models.schemas import ProviderCreate, SelectiveIgnoreRule
from voidswitch.services.provider_error_policy import (
    ErrorProvenance,
    PolicyAction,
    evaluate_provider_error_policy,
    match_selective_ignore_rule,
)


def _decision(
    *,
    mode: str = "auto",
    status: int = 403,
    headers: dict[str, str] | None = None,
    body: object = None,
    rules: list[SelectiveIgnoreRule] | None = None,
):
    return evaluate_provider_error_policy(
        new_api_mode=mode,
        selective_ignore_rules=rules or [],
        status_code=status,
        headers=headers or {},
        body=body,
        original_classification="key_invalid",
    )


def test_provider_policy_defaults_and_mode_validation():
    provider = ProviderCreate(name="relay")
    assert provider.new_api_mode == "auto"
    assert provider.protected_error_retry_enabled is False
    assert provider.selective_ignore_rules == []

    with pytest.raises(ValidationError):
        ProviderCreate(name="relay", new_api_mode=cast(Any, "sometimes"))


@pytest.mark.parametrize("value", [None, "", "   ", 123])
def test_new_api_requires_a_non_empty_string_error_type(value):
    decision = _decision(
        mode="enabled",
        body={"error": {"type": value}},
    )
    assert decision.provenance is ErrorProvenance.UNKNOWN
    assert decision.action is PolicyAction.USE_ADAPTER


def test_new_api_auto_detection_is_per_response_and_header_case_insensitive():
    origin = {"error": {"type": "upstream_error"}}
    assert (
        _decision(headers={"x-new-api-version": "v1"}, body=origin).action is PolicyAction.PROTECT
    )
    assert (
        _decision(headers={"X-New-Api-Version": "  "}, body=origin).provenance
        is ErrorProvenance.NOT_EVALUATED
    )
    assert _decision(body=origin).provenance is ErrorProvenance.NOT_EVALUATED


def test_new_api_modes_and_provenance():
    origin = {"error": {"type": "upstream_error"}}
    relay = {"error": {"type": "new_api_error"}}

    assert _decision(mode="enabled", body=origin).provenance is ErrorProvenance.ORIGIN
    assert _decision(mode="enabled", body=origin).action is PolicyAction.PROTECT
    assert _decision(mode="enabled", body=relay).provenance is ErrorProvenance.RELAY
    assert _decision(mode="enabled", body=relay).action is PolicyAction.USE_ADAPTER
    assert (
        _decision(mode="disabled", headers={"X-New-Api-Version": "1"}, body=origin).provenance
        is ErrorProvenance.NOT_EVALUATED
    )


@pytest.mark.parametrize("status", [401, 402, 403, 429])
def test_only_protected_origin_statuses_override_adapter(status: int):
    assert (
        _decision(mode="enabled", status=status, body={"error": {"type": "upstream_error"}}).action
        is PolicyAction.PROTECT
    )


def test_other_origin_status_preserves_adapter_classification():
    decision = _decision(mode="enabled", status=400, body={"error": {"type": "upstream_error"}})
    assert decision.provenance is ErrorProvenance.ORIGIN
    assert decision.action is PolicyAction.USE_ADAPTER
    assert decision.final_classification == "key_invalid"


def test_rule_normalizes_status_expression_and_rejects_invalid_rules():
    rule = SelectiveIgnoreRule(
        name="  policy  ",
        status_codes=" 400 - 403, 409, 402-405, 451 ",
    )
    assert rule.name == "policy"
    assert rule.status_codes == "400-405,409,451"
    body_only = SelectiveIgnoreRule(name="body", status_codes=" ", body_substrings=[" timeout "])
    assert body_only.status_codes is None
    assert body_only.body_substrings == ["timeout"]

    for expression in ("nope", "99", "600", "403-400", "400,,401"):
        with pytest.raises(ValidationError):
            SelectiveIgnoreRule(name="bad", status_codes=expression)
    with pytest.raises(ValidationError):
        SelectiveIgnoreRule(name="blank", status_codes=None, body_substrings=[])
    with pytest.raises(ValidationError):
        SelectiveIgnoreRule(name=" ", status_codes="400")
    with pytest.raises(ValidationError):
        SelectiveIgnoreRule(name="bad body", body_substrings=["  "])


def test_rule_matching_uses_and_or_order_and_disabled_rules():
    rules = [
        SelectiveIgnoreRule(name="disabled", enabled=False, status_codes="400"),
        SelectiveIgnoreRule(
            name="wrong status", status_codes="401", body_substrings=["Quota", "Capacity"]
        ),
        SelectiveIgnoreRule(
            name="first", status_codes="400-403", body_substrings=["Quota", "Capacity"]
        ),
        SelectiveIgnoreRule(name="later", status_codes="403"),
    ]
    match = match_selective_ignore_rule(rules, status_code=403, body="NO CAPACITY remaining")
    assert match is not None
    assert match.rule_name == "first"
    assert match.status_matched is True
    assert match.body_matched is True


def test_json_body_matching_recurses_over_values_but_not_keys_and_handles_unicode():
    value_rule = SelectiveIgnoreRule(name="unicode", body_substrings=["STRASSE"])
    key_rule = SelectiveIgnoreRule(name="keys ignored", body_substrings=["secret marker"])
    body = {"secret marker": {"nested": [1, "Straße"]}}
    assert match_selective_ignore_rule([value_rule], status_code=500, body=body) is not None
    assert match_selective_ignore_rule([key_rule], status_code=500, body=body) is None


def test_body_matching_only_inspects_first_64_kib_of_aggregate_utf8_text():
    rule = SelectiveIgnoreRule(name="bounded", body_substrings=["needle"])
    assert (
        match_selective_ignore_rule(
            [rule], status_code=500, body={"first": "x" * 65536, "second": "needle"}
        )
        is None
    )
    assert (
        match_selective_ignore_rule(
            [rule], status_code=500, body={"first": "x" * 65520, "second": "needle"}
        )
        is not None
    )


def test_custom_rule_takes_priority_over_new_api_provenance():
    rule = SelectiveIgnoreRule(name="custom", status_codes="400")
    decision = _decision(
        mode="enabled",
        status=400,
        body={"error": {"type": "new_api_error"}},
        rules=[rule],
    )
    assert decision.action is PolicyAction.PROTECT
    assert decision.matched_rule_name == "custom"
    assert decision.provenance is ErrorProvenance.NOT_EVALUATED
