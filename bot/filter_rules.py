import json


def extract_known_keywords(extras: list[str | None]) -> list[str]:
    """Parse extra JSON strings and return dedup'd, sorted union of all keywords."""
    keywords = set()
    for extra_json in extras:
        if not extra_json:
            continue
        try:
            rules = json.loads(extra_json)
            for field in ["required", "any", "exclude"]:
                words = rules.get(field, [])
                if words:
                    keywords.update(w.lower() for w in words if w)
        except (json.JSONDecodeError, TypeError):
            continue
    return sorted(keywords)
