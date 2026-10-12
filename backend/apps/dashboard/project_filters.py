import json

from rest_framework.exceptions import ValidationError


def parse_project_selections(query_params, project_groups):
    """Validate exact dialer/project pairs before building the report predicate."""
    if "projects" not in query_params:
        return None
    error = {"projects": "Choose up to 200 accessible dialer projects."}
    if (
        hasattr(query_params, "getlist") and len(query_params.getlist("projects")) != 1
    ) or any(query_params.get(key, "").strip() for key in ("project", "dialer")):
        raise ValidationError(
            {"projects": "Use either projects or the single-project filters."}
        )
    raw = query_params["projects"]
    if isinstance(raw, str):
        if len(raw) > 64_000:
            raise ValidationError(error)
        try:
            selections = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise ValidationError(error) from exc
    else:
        selections = raw
    if not isinstance(selections, list) or len(selections) > 200:
        raise ValidationError(error)
    result, seen = [], set()
    for selection in selections:
        if (
            not isinstance(selection, dict)
            or set(selection) != {"dialer", "project"}
            or not isinstance(selection["dialer"], str)
            or not isinstance(selection["project"], str)
            or selection["dialer"] not in project_groups
            or selection["project"]
            not in project_groups[selection["dialer"]]["projects"]
        ):
            raise ValidationError(error)
        pair = (selection["dialer"], selection["project"])
        if pair not in seen:
            seen.add(pair)
            result.append({"dialer": pair[0], "project": pair[1]})
    return result
