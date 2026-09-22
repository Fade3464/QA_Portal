from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID

from rest_framework.exceptions import ValidationError


SCORECARD_VERSION = "outbound-sales-v2"

CALL_EVALUATION_TYPES = {
    "full",
    "partial",
    "not_evaluable",
    "agent_premature",
}
CATEGORY_APPLICABILITY_STATES = {
    "applicable",
    "not_reached",
    "missed_opportunity",
}
CRITERION_APPLICABILITY_STATES = {
    "applicable",
    "not_reached",
}
CATEGORY_REASON_VALUES = {
    "caller_ended",
    "customer_declined",
    "wrong_party",
    "voicemail",
    "technical_interruption",
    "transferred",
    "not_required",
    "agent_failed_to_progress",
    "agent_ended_call",
    "other",
}

SCORECARD = (
    {
        "key": "opening",
        "label": "Opening & Introduction",
        "max_score": 10,
        "criteria": (
            ("professional_greeting", "Professional greeting", 2),
            ("correct_identification", "Correct agent/company identification", 2),
            ("required_introduction", "Required introduction or disclosure", 2),
            ("clear_call_reason", "Clear reason for the call", 2),
            ("customer_engagement", "Gains customer engagement", 2),
        ),
    },
    {
        "key": "communication",
        "label": "Communication & Rapport",
        "max_score": 15,
        "criteria": (
            ("clear_communication", "Clear and professional communication", 3),
            ("active_listening", "Active listening", 3),
            ("tone_confidence", "Appropriate tone and confidence", 3),
            ("builds_rapport", "Builds rapport", 3),
            ("avoids_interruptions", "Avoids unnecessary interruptions", 3),
        ),
    },
    {
        "key": "discovery",
        "label": "Discovery & Needs Analysis",
        "max_score": 15,
        "criteria": (
            ("discovery_questions", "Uses relevant discovery questions", 4),
            ("identifies_needs", "Identifies customer needs", 4),
            ("confirms_understanding", "Confirms understanding", 3),
            ("buying_motivation", "Identifies buying motivation", 2),
            ("concerns_objections", "Identifies concerns or objections", 2),
        ),
    },
    {
        "key": "presentation",
        "label": "Product / Service Presentation",
        "max_score": 15,
        "criteria": (
            ("solution_match", "Matches solution to customer needs", 4),
            ("benefits_explained", "Explains key benefits clearly", 4),
            ("accurate_information", "Provides accurate information", 3),
            ("approved_value_proposition", "Uses approved value proposition", 2),
            (
                "avoids_information_overload",
                "Avoids unnecessary information overload",
                2,
            ),
        ),
    },
    {
        "key": "objection_handling",
        "label": "Objection Handling",
        "max_score": 10,
        "criteria": (
            ("real_objection", "Identifies the real objection", 3),
            ("acknowledges_concern", "Acknowledges customer concern", 2),
            ("appropriate_response", "Provides an appropriate response", 3),
            ("moves_sale_forward", "Attempts to move the sale forward", 2),
        ),
    },
    {
        "key": "sales_closing",
        "label": "Sales Closing",
        "max_score": 15,
        "criteria": (
            ("appropriate_close", "Attempts an appropriate close", 4),
            ("confirms_interest", "Confirms customer interest", 3),
            ("closing_technique", "Uses an effective closing technique", 3),
            ("confirms_next_steps", "Confirms next steps or commitment", 3),
            ("appropriate_urgency", "Creates urgency without pressure or deception", 2),
        ),
    },
    {
        "key": "compliance",
        "label": "Compliance & Accuracy",
        "max_score": 15,
        "criteria": (
            ("required_disclosures", "Provides required disclosures", 4),
            ("compliance_accuracy", "Provides accurate information", 3),
            ("no_misrepresentation", "Does not misrepresent products or services", 3),
            ("campaign_requirements", "Follows campaign/client requirements", 3),
            ("protects_information", "Protects customer information", 2),
        ),
    },
    {
        "key": "crm_call_control",
        "label": "CRM Documentation & Call Control",
        "max_score": 5,
        "criteria": (
            ("correct_disposition", "Correct call disposition", 2),
            ("accurate_crm_notes", "Accurate CRM notes", 2),
            ("call_structure", "Maintains appropriate call structure", 1),
        ),
    },
)

CRITICAL_ERRORS = (
    ("misrepresentation", "Misrepresentation or false promises"),
    (
        "unauthorized_commitment",
        "Unauthorized pricing, discount, or contractual commitment",
    ),
    ("missing_disclosure", "Failure to provide mandatory disclosures"),
    ("deliberately_misleading", "Deliberate misleading statements"),
    ("abuse", "Abuse, harassment, or discriminatory language"),
    ("crm_falsification", "Falsification of CRM information or sales records"),
    (
        "data_misuse",
        "Unauthorized collection, sharing, or misuse of customer information",
    ),
    (
        "requirement_circumvention",
        "Circumvention of legal, compliance, client, or campaign requirements",
    ),
    ("fraud", "Fraudulent or intentionally deceptive sales practices"),
    ("non_serious_attitude", "Non-serious attitude"),
    ("wasted_lead", "Wasted lead (agent did not respond to the customer)"),
)


def scorecard_payload() -> dict:
    return {
        "version": SCORECARD_VERSION,
        "max_score": 100,
        "benchmark": 85,
        "minimum_scored_coverage": 20,
        "evaluation_types": [
            {"value": "full", "label": "Full call"},
            {"value": "partial", "label": "Partial call"},
            {"value": "not_evaluable", "label": "Not evaluable"},
            {"value": "agent_premature", "label": "Agent ended early"},
        ],
        "applicability_states": [
            {"value": "applicable", "label": "Applicable"},
            {"value": "not_reached", "label": "Not reached"},
            {"value": "missed_opportunity", "label": "Missed opportunity"},
        ],
        "applicability_reasons": [
            {"value": "caller_ended", "label": "Caller ended the call"},
            {"value": "customer_declined", "label": "Customer declined to continue"},
            {"value": "wrong_party", "label": "Wrong party / unavailable"},
            {"value": "voicemail", "label": "Voicemail or no interaction"},
            {"value": "technical_interruption", "label": "Technical interruption"},
            {"value": "transferred", "label": "Call transferred"},
            {"value": "not_required", "label": "Not required for this call"},
            {"value": "agent_failed_to_progress", "label": "Agent did not progress the call"},
            {"value": "agent_ended_call", "label": "Agent ended the call early"},
            {"value": "other", "label": "Other"},
        ],
        "categories": [
            {
                **{key: value for key, value in category.items() if key != "criteria"},
                "criteria": [
                    {"key": key, "label": label, "max_score": maximum}
                    for key, label, maximum in category["criteria"]
                ],
            }
            for category in SCORECARD
        ],
        "critical_errors": [
            {"value": value, "label": label} for value, label in CRITICAL_ERRORS
        ],
    }


def calculate_score(scores, *, require_complete: bool) -> Decimal:
    if not isinstance(scores, dict):
        raise ValidationError({"scores": "Scores must be an object."})
    criteria = {
        key: maximum
        for category in SCORECARD
        for key, _label, maximum in category["criteria"]
    }
    unknown = set(scores) - set(criteria)
    if unknown:
        raise ValidationError({"scores": f"Unknown criterion: {sorted(unknown)[0]}"})
    if require_complete and set(scores) != set(criteria):
        missing = set(criteria) - set(scores)
        raise ValidationError(
            {
                "scores": f"Score every criterion before submission. Missing: {sorted(missing)[0]}"
            }
        )
    total = Decimal("0")
    for key, value in scores.items():
        try:
            points = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError({"scores": f"{key} must be a number."}) from exc
        if points < 0 or points > criteria[key] or points.as_tuple().exponent < -2:
            raise ValidationError(
                {
                    "scores": f"{key} must be between 0 and {criteria[key]} with at most two decimals."
                }
            )
        total += points
    return total.quantize(Decimal("0.01"))


@dataclass(frozen=True)
class EvaluationResult:
    score: Decimal | None
    earned_points: Decimal
    applicable_points: Decimal
    coverage: Decimal
    coverage_tier: str
    scores: dict[str, float]
    category_applicability: dict[str, str]
    category_applicability_reasons: dict[str, str]
    criterion_applicability: dict[str, str]


def calculate_evaluation(
    scores,
    *,
    evaluation_type: str = "full",
    category_applicability=None,
    category_applicability_reasons=None,
    criterion_applicability=None,
    require_complete: bool,
) -> EvaluationResult:
    """Calculate normalized QA quality across only material that was reached.

    Heading- and criterion-level ``not_reached`` values are excluded from the
    denominator. A heading marked as a missed opportunity remains fully in the
    denominator and receives zero points.
    """
    if evaluation_type not in CALL_EVALUATION_TYPES:
        raise ValidationError({"evaluation_type": "Unsupported call evaluation type."})
    if not isinstance(category_applicability or {}, dict):
        raise ValidationError(
            {"category_applicability": "Heading applicability must be an object."}
        )
    if not isinstance(category_applicability_reasons or {}, dict):
        raise ValidationError(
            {"category_applicability_reasons": "Heading reasons must be an object."}
        )
    if not isinstance(criterion_applicability or {}, dict):
        raise ValidationError(
            {"criterion_applicability": "Sub-heading applicability must be an object."}
        )

    categories = {category["key"]: category for category in SCORECARD}
    criteria = {
        criterion_key: (category["key"], maximum)
        for category in SCORECARD
        for criterion_key, _label, maximum in category["criteria"]
    }
    supplied_states = category_applicability or {}
    supplied_reasons = category_applicability_reasons or {}
    supplied_criterion_states = criterion_applicability or {}

    unknown_states = set(supplied_states) - set(categories)
    unknown_reasons = set(supplied_reasons) - set(categories)
    unknown_criterion_states = set(supplied_criterion_states) - set(criteria)
    if unknown_states:
        raise ValidationError(
            {"category_applicability": f"Unknown heading: {sorted(unknown_states)[0]}"}
        )
    if unknown_reasons:
        raise ValidationError(
            {
                "category_applicability_reasons": (
                    f"Unknown heading: {sorted(unknown_reasons)[0]}"
                )
            }
        )
    if unknown_criterion_states:
        raise ValidationError(
            {
                "criterion_applicability": (
                    f"Unknown sub-heading: {sorted(unknown_criterion_states)[0]}"
                )
            }
        )

    default_state = (
        "not_reached"
        if evaluation_type in {"partial", "not_evaluable"}
        else "applicable"
    )
    states = {key: supplied_states.get(key, default_state) for key in categories}
    invalid_state = next(
        (state for state in states.values() if state not in CATEGORY_APPLICABILITY_STATES),
        None,
    )
    if invalid_state:
        raise ValidationError(
            {"category_applicability": f"Unsupported heading state: {invalid_state}"}
        )

    criterion_states = {
        key: supplied_criterion_states.get(key, "applicable") for key in criteria
    }
    invalid_criterion_state = next(
        (
            state
            for state in criterion_states.values()
            if state not in CRITERION_APPLICABILITY_STATES
        ),
        None,
    )
    if invalid_criterion_state:
        raise ValidationError(
            {
                "criterion_applicability": (
                    f"Unsupported sub-heading state: {invalid_criterion_state}"
                )
            }
        )

    if evaluation_type == "full" and any(
        state != "applicable" for state in states.values()
    ):
        raise ValidationError(
            {"category_applicability": "A full call must include every heading."}
        )
    if evaluation_type == "full" and any(
        state != "applicable" for state in criterion_states.values()
    ):
        raise ValidationError(
            {"criterion_applicability": "A full call must include every sub-heading."}
        )
    if evaluation_type == "not_evaluable" and any(
        state != "not_reached" for state in states.values()
    ):
        raise ValidationError(
            {
                "category_applicability": (
                    "A non-evaluable call cannot contain scored headings."
                )
            }
        )
    if require_complete and evaluation_type == "agent_premature" and not any(
        state == "missed_opportunity" for state in states.values()
    ):
        raise ValidationError(
            {
                "category_applicability": (
                    "Mark at least one heading as a missed opportunity when the agent ended early."
                )
            }
        )

    reasons = {}
    for key, reason in supplied_reasons.items():
        if not isinstance(reason, str) or reason not in CATEGORY_REASON_VALUES:
            raise ValidationError(
                {
                    "category_applicability_reasons": (
                        f"Unsupported reason for {key}."
                    )
                }
            )
        if states[key] != "applicable":
            reasons[key] = reason

    # Partial calls intentionally do not require a reason for each Not Reached
    # heading. Agent-ended-early evaluations keep the reason requirement.
    if require_complete and evaluation_type == "agent_premature":
        missing_reason = next(
            (
                key
                for key, state in states.items()
                if state != "applicable" and key not in reasons
            ),
            None,
        )
        if missing_reason:
            raise ValidationError(
                {
                    "category_applicability_reasons": (
                        f"Select a reason for {categories[missing_reason]['label']}."
                    )
                }
            )

    calculate_score(scores, require_complete=False)
    normalized_scores: dict[str, float] = {}
    earned = Decimal("0")
    applicable = Decimal("0")

    for category_key, category in categories.items():
        category_state = states[category_key]
        if category_state == "not_reached":
            continue

        for criterion_key, _label, maximum in category["criteria"]:
            maximum_points = Decimal(str(maximum))

            if category_state == "missed_opportunity":
                applicable += maximum_points
                normalized_scores[criterion_key] = 0
                continue

            if criterion_states[criterion_key] == "not_reached":
                continue

            applicable += maximum_points
            if criterion_key not in scores:
                if require_complete:
                    raise ValidationError(
                        {
                            "scores": (
                                "Score every applicable criterion before submission. "
                                f"Missing: {criterion_key}"
                            )
                        }
                    )
                continue

            points = Decimal(str(scores[criterion_key]))
            if points < 0 or points > maximum or points.as_tuple().exponent < -2:
                raise ValidationError(
                    {
                        "scores": (
                            f"{criterion_key} must be between 0 and {maximum} "
                            "with at most two decimals."
                        )
                    }
                )
            earned += points
            normalized_scores[criterion_key] = float(points)

    coverage = applicable.quantize(Decimal("0.01"))
    if coverage < 20:
        tier = "insufficient"
        score = None
    elif coverage < 60:
        tier = "limited"
        score = (earned / applicable * 100).quantize(Decimal("0.01"))
    elif coverage < 85:
        tier = "partial"
        score = (earned / applicable * 100).quantize(Decimal("0.01"))
    else:
        tier = "full"
        score = (earned / applicable * 100).quantize(Decimal("0.01"))

    return EvaluationResult(
        score=score,
        earned_points=earned.quantize(Decimal("0.01")),
        applicable_points=applicable.quantize(Decimal("0.01")),
        coverage=coverage,
        coverage_tier=tier,
        scores=normalized_scores,
        category_applicability=states,
        category_applicability_reasons=reasons,
        criterion_applicability=criterion_states,
    )

def _validate_evidence(
    evidence,
    *,
    allowed_keys: set[str],
    field_name: str,
    entry_label: str,
    duration_seconds: int | None = None,
) -> dict:
    if not isinstance(evidence, dict):
        raise ValidationError({field_name: "Evidence must be an object."})
    unknown = set(evidence) - allowed_keys
    if unknown:
        raise ValidationError({field_name: f"Unknown {entry_label}: {sorted(unknown)[0]}"})
    if len(evidence) > len(allowed_keys):
        raise ValidationError({field_name: f"Too many {entry_label} entries."})

    normalized = {}
    total_patches = 0
    known_duration_ms = duration_seconds * 1000 if duration_seconds else None
    for criterion_key, entry in evidence.items():
        if not isinstance(entry, dict):
            raise ValidationError(
                {field_name: f"{criterion_key} must be an object."}
            )
        unexpected = set(entry) - {"comment", "patches"}
        if unexpected:
            raise ValidationError(
                {
                    field_name: (
                        f"Unsupported field for {criterion_key}: {sorted(unexpected)[0]}"
                    )
                }
            )
        comment = entry.get("comment", "")
        patches = entry.get("patches", [])
        if not isinstance(comment, str) or len(comment) > 2000:
            raise ValidationError(
                {
                    field_name: (
                        f"The comment for {criterion_key} must be at most 2000 characters."
                    )
                }
            )
        if not isinstance(patches, list) or len(patches) > 20:
            raise ValidationError(
                {
                    field_name: (
                        f"{criterion_key} can contain at most 20 timestamp patches."
                    )
                }
            )
        total_patches += len(patches)
        if total_patches > 200:
            raise ValidationError(
                {field_name: "A report can contain at most 200 patches."}
            )

        normalized_patches = []
        seen_ids = set()
        for position, patch in enumerate(patches, start=1):
            if not isinstance(patch, dict):
                raise ValidationError(
                    {
                        field_name: (
                            f"Patch {position} for {criterion_key} must be an object."
                        )
                    }
                )
            unexpected_patch = set(patch) - {"id", "start_ms", "end_ms", "comment"}
            if unexpected_patch:
                raise ValidationError(
                    {
                        field_name: (
                            f"Unsupported patch field: {sorted(unexpected_patch)[0]}"
                        )
                    }
                )
            patch_id = patch.get("id")
            try:
                normalized_id = str(UUID(str(patch_id)))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValidationError(
                    {
                        field_name: (
                            f"Patch {position} for {criterion_key} has an invalid ID."
                        )
                    }
                ) from exc
            if normalized_id in seen_ids:
                raise ValidationError(
                    {field_name: f"Duplicate patch ID for {criterion_key}."}
                )
            seen_ids.add(normalized_id)
            start_ms = patch.get("start_ms")
            end_ms = patch.get("end_ms")
            patch_comment = patch.get("comment", "")
            if (
                isinstance(start_ms, bool)
                or isinstance(end_ms, bool)
                or not isinstance(start_ms, int)
                or not isinstance(end_ms, int)
            ):
                raise ValidationError(
                    {
                        field_name: (
                            f"Patch {position} for {criterion_key} requires integer timestamps."
                        )
                    }
                )
            if start_ms < 0 or end_ms <= start_ms:
                raise ValidationError(
                    {
                        field_name: (
                            f"Patch {position} for {criterion_key} must end after it starts."
                        )
                    }
                )
            if end_ms > 86_400_000:
                raise ValidationError(
                    {field_name: "Patch timestamps cannot exceed 24 hours."}
                )
            # Stored duration is rounded to a whole second, so allow one second
            # of tolerance while still enforcing the recording boundary.
            if known_duration_ms and end_ms > known_duration_ms + 1000:
                raise ValidationError(
                    {
                        field_name: (
                            f"Patch {position} for {criterion_key} exceeds the recording duration."
                        )
                    }
                )
            if not isinstance(patch_comment, str) or len(patch_comment) > 500:
                raise ValidationError(
                    {
                        field_name: (
                            f"Patch {position} for {criterion_key} has an invalid comment."
                        )
                    }
                )
            normalized_patches.append(
                {
                    "id": normalized_id,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "comment": patch_comment.strip(),
                }
            )

        normalized_patches.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
        for previous, current in zip(
            normalized_patches, normalized_patches[1:], strict=False
        ):
            if current["start_ms"] < previous["end_ms"]:
                raise ValidationError(
                    {
                        field_name: (
                            f"Timestamp patches for {criterion_key} cannot overlap."
                        )
                    }
                )
        if comment.strip() or normalized_patches:
            normalized[criterion_key] = {
                "comment": comment.strip(),
                "patches": normalized_patches,
            }
    return normalized


def validate_criterion_evidence(
    evidence, *, duration_seconds: int | None = None
) -> dict:
    criteria = {
        key for category in SCORECARD for key, _label, _maximum in category["criteria"]
    }
    return _validate_evidence(
        evidence,
        allowed_keys=criteria,
        field_name="criterion_evidence",
        entry_label="criterion",
        duration_seconds=duration_seconds,
    )


def validate_critical_error_evidence(
    evidence, *, duration_seconds: int | None = None
) -> dict:
    return _validate_evidence(
        evidence,
        allowed_keys={value for value, _label in CRITICAL_ERRORS},
        field_name="critical_error_evidence",
        entry_label="critical error",
        duration_seconds=duration_seconds,
    )


def rating_for(score: Decimal | None, has_critical_error: bool) -> tuple[str, str]:
    if has_critical_error:
        return "automatic_fail", "immediate_escalation"
    if score is None:
        return "not_evaluable", "not_evaluable"
    if score >= 95:
        return "excellent", "exceeds_expectations"
    if score >= 90:
        return "very_good", "meets_expectations"
    if score >= 85:
        return "good", "meets_minimum_standard"
    if score >= 80:
        return "needs_improvement", "coaching_required"
    return "unsatisfactory", "performance_action_required"
