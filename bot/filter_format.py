def render_boolean_expression(rules: dict) -> str:
    """Render filter rules as a human-readable boolean expression.

    Example: {"required": ["PHP"], "any": ["Senior","Lead"], "exclude": ["WordPress"]}
    -> "PHP AND (Senior OR Lead) AND NOT WordPress"
    """
    required = rules.get("required") or []
    any_kw   = rules.get("any") or []
    exclude  = rules.get("exclude") or []

    if not required and not any_kw and not exclude:
        return "(no rules — matches nothing)"

    segments = []

    if required:
        segments.append(" AND ".join(required))

    if any_kw:
        if len(any_kw) == 1:
            segments.append(any_kw[0])
        else:
            segments.append("(" + " OR ".join(any_kw) + ")")

    if exclude:
        if len(exclude) == 1:
            segments.append(f"NOT {exclude[0]}")
        else:
            segments.append("NOT (" + " OR ".join(exclude) + ")")

    return " AND ".join(segments)


def render_preview_box(preview: dict, rules: dict, width: int = 45) -> str:
    """Render a preview box with match count and sample messages.

    preview = {"count": int, "samples": [{"id", "description", "tg_message_link"}, ...]}
    Returns plain text with box-drawing chars.
    """
    count = preview.get("count", 0)
    samples = preview.get("samples", [])

    if count == 0:
        return "No matching vacancies yet"

    lines = [
        "┌" + "─" * (width - 2) + "┐",
        f"│ {count} matching vacancies" + " " * (width - len(str(count)) - 20) + "│",
        "│" + " " * (width - 2) + "│",
    ]

    required = set(kw.lower() for kw in (rules.get("required") or []) if kw)
    any_kw   = set(kw.lower() for kw in (rules.get("any") or []) if kw)

    for sample in samples[:3]:
        desc = sample.get("description", "")
        title = desc.split("\n")[0] if desc else ""
        title = title[:width - 4].rstrip()
        if len(title) < len(desc.split("\n")[0] if desc else ""):
            title += "…"

        lines.append(f"│ {title:<{width - 3}}│")

        matched_words = set()
        desc_lower = desc.lower()
        for word in required | any_kw:
            if word in desc_lower:
                matched_words.add(word)

        if matched_words:
            tags = " · ".join(sorted(matched_words))
            tags = tags[:width - 4]
            lines.append(f"│ {tags:<{width - 3}}│")

        lines.append("│" + " " * (width - 2) + "│")

    lines.append("└" + "─" * (width - 2) + "┘")

    return "\n".join(lines)
