"""Tests for workflow path resolution, interpolation, and choice rule evaluation."""

from __future__ import annotations

from nanobot.workflow.evaluator import (
    evaluate_choice,
    interpolate_obj,
    interpolate_template,
    resolve_path,
    set_path,
)
from nanobot.workflow.schema import ChoiceRule


def test_resolve_path() -> None:
    data = {
        "analysis": {
            "urgency": "high",
            "score": 95.5,
            "items": ["apple", "banana"],
            "nested": [{"id": 1}, {"id": 2}],
        },
        "flag": True,
    }

    assert resolve_path(data, "$.analysis.urgency") == "high"
    assert resolve_path(data, "analysis.urgency") == "high"
    assert resolve_path(data, "analysis.score") == 95.5
    assert resolve_path(data, "flag") is True
    assert resolve_path(data, "analysis.items[1]") == "banana"
    assert resolve_path(data, "analysis.nested[0].id") == 1
    assert resolve_path(data, "$.analysis.missing") is None
    assert resolve_path(data, "$.missing.deep") is None


def test_set_path() -> None:
    data: dict[str, object] = {}
    set_path(data, "$.inbox.latest", "message 1")
    assert data == {"inbox": {"latest": "message 1"}}

    set_path(data, "status", "complete")
    assert data["status"] == "complete"

    set_path(data, "inbox.count", 42)
    assert data["inbox"] == {"latest": "message 1", "count": 42}


def test_interpolate_template() -> None:
    context = {
        "user": "Alice",
        "analysis": {"category": "billing", "amount": 150},
    }
    tpl = "Hello {{$.user}}, your issue is in {{analysis.category}} with amount ${{analysis.amount}}."
    rendered = interpolate_template(tpl, context)
    assert rendered == "Hello Alice, your issue is in billing with amount $150."

    # Braced ${...} and {{...}} are supported; bare text remains literal
    tpl2 = "Hello ${user}, details: ${$.analysis.category}, literal: $.analysis.category."
    rendered2 = interpolate_template(tpl2, context)
    assert rendered2 == "Hello Alice, details: billing, literal: $.analysis.category."

    # Recursive object interpolation
    params = {
        "text": "User: {{$.user}}",
        "nested": {"details": "{{$.analysis.category}}"},
        "list": ["Amount: {{$.analysis.amount}}", 123],
    }
    interpolated = interpolate_obj(params, context)
    assert interpolated == {
        "text": "User: Alice",
        "nested": {"details": "billing"},
        "list": ["Amount: 150", 123],
    }


def test_evaluate_choice_rules() -> None:
    ctx = {
        "ticket": {
            "urgency": "high",
            "score": 85,
            "tags": ["vip", "escalation"],
            "resolved": False,
            "notes": None,
        }
    }

    # Equality
    assert evaluate_choice(ChoiceRule(variable="$.ticket.urgency", equals="high", next="step_a"), ctx) is True
    assert evaluate_choice(ChoiceRule(variable="$.ticket.urgency", equals="low", next="step_a"), ctx) is False

    # Inequality
    assert evaluate_choice(ChoiceRule(variable="$.ticket.urgency", not_equals="low", next="step_a"), ctx) is True

    # Numeric comparisons
    assert evaluate_choice(ChoiceRule(variable="$.ticket.score", numeric_gt=80, next="step_a"), ctx) is True
    assert evaluate_choice(ChoiceRule(variable="$.ticket.score", numeric_gt=90, next="step_a"), ctx) is False
    assert evaluate_choice(ChoiceRule(variable="$.ticket.score", numeric_lte=85, next="step_a"), ctx) is True

    # Boolean & Null
    assert evaluate_choice(ChoiceRule(variable="$.ticket.resolved", boolean_equals=False, next="step_a"), ctx) is True
    assert evaluate_choice(ChoiceRule(variable="$.ticket.notes", is_null=True, next="step_a"), ctx) is True
    assert evaluate_choice(ChoiceRule(variable="$.ticket.urgency", is_null=False, next="step_a"), ctx) is True

    # Contains & String matching
    assert evaluate_choice(ChoiceRule(variable="$.ticket.tags", contains="vip", next="step_a"), ctx) is True
    assert evaluate_choice(ChoiceRule(variable="$.ticket.urgency", starts_with="hi", next="step_a"), ctx) is True
    assert evaluate_choice(ChoiceRule(variable="$.ticket.urgency", ends_with="gh", next="step_a"), ctx) is True
