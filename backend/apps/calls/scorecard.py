from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from rest_framework.exceptions import ValidationError


SCORECARD_VERSION = "outbound-sales-v1"

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
)


def scorecard_payload() -> dict:
    return {
        "version": SCORECARD_VERSION,
        "max_score": 100,
        "benchmark": 85,
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


def validate_criterion_evidence(
    evidence, *, duration_seconds: int | None = None
) -> dict:
    if not isinstance(evidence, dict):
        raise ValidationError({"criterion_evidence": "Evidence must be an object."})
    criteria = {
        key for category in SCORECARD for key, _label, _maximum in category["criteria"]
    }
    unknown = set(evidence) - criteria
    if unknown:
        raise ValidationError(
            {"criterion_evidence": f"Unknown criterion: {sorted(unknown)[0]}"}
        )
    if len(evidence) > len(criteria):
        raise ValidationError({"criterion_evidence": "Too many criterion entries."})

    normalized = {}
    total_patches = 0
    known_duration_ms = duration_seconds * 1000 if duration_seconds else None
    for criterion_key, entry in evidence.items():
        if not isinstance(entry, dict):
            raise ValidationError(
                {"criterion_evidence": f"{criterion_key} must be an object."}
            )
        unexpected = set(entry) - {"comment", "patches"}
        if unexpected:
            raise ValidationError(
                {
                    "criterion_evidence": (
                        f"Unsupported field for {criterion_key}: {sorted(unexpected)[0]}"
                    )
                }
            )
        comment = entry.get("comment", "")
        patches = entry.get("patches", [])
        if not isinstance(comment, str) or len(comment) > 2000:
            raise ValidationError(
                {
                    "criterion_evidence": (
                        f"The comment for {criterion_key} must be at most 2000 characters."
                    )
                }
            )
        if not isinstance(patches, list) or len(patches) > 20:
            raise ValidationError(
                {
                    "criterion_evidence": (
                        f"{criterion_key} can contain at most 20 timestamp patches."
                    )
                }
            )
        total_patches += len(patches)
        if total_patches > 200:
            raise ValidationError(
                {"criterion_evidence": "A report can contain at most 200 patches."}
            )

        normalized_patches = []
        seen_ids = set()
        for position, patch in enumerate(patches, start=1):
            if not isinstance(patch, dict):
                raise ValidationError(
                    {
                        "criterion_evidence": (
                            f"Patch {position} for {criterion_key} must be an object."
                        )
                    }
                )
            unexpected_patch = set(patch) - {"id", "start_ms", "end_ms", "comment"}
            if unexpected_patch:
                raise ValidationError(
                    {
                        "criterion_evidence": (
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
                        "criterion_evidence": (
                            f"Patch {position} for {criterion_key} has an invalid ID."
                        )
                    }
                ) from exc
            if normalized_id in seen_ids:
                raise ValidationError(
                    {"criterion_evidence": f"Duplicate patch ID for {criterion_key}."}
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
                        "criterion_evidence": (
                            f"Patch {position} for {criterion_key} requires integer timestamps."
                        )
                    }
                )
            if start_ms < 0 or end_ms <= start_ms:
                raise ValidationError(
                    {
                        "criterion_evidence": (
                            f"Patch {position} for {criterion_key} must end after it starts."
                        )
                    }
                )
            if end_ms > 86_400_000:
                raise ValidationError(
                    {"criterion_evidence": "Patch timestamps cannot exceed 24 hours."}
                )
            # Stored duration is rounded to a whole second, so allow one second
            # of tolerance while still enforcing the recording boundary.
            if known_duration_ms and end_ms > known_duration_ms + 1000:
                raise ValidationError(
                    {
                        "criterion_evidence": (
                            f"Patch {position} for {criterion_key} exceeds the recording duration."
                        )
                    }
                )
            if not isinstance(patch_comment, str) or len(patch_comment) > 500:
                raise ValidationError(
                    {
                        "criterion_evidence": (
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
                        "criterion_evidence": (
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


def rating_for(score: Decimal, has_critical_error: bool) -> tuple[str, str]:
    if has_critical_error:
        return "automatic_fail", "immediate_escalation"
    if score >= 95:
        return "excellent", "exceeds_expectations"
    if score >= 90:
        return "very_good", "meets_expectations"
    if score >= 85:
        return "good", "meets_minimum_standard"
    if score >= 80:
        return "needs_improvement", "coaching_required"
    return "unsatisfactory", "performance_action_required"
