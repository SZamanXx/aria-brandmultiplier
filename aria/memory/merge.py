"""
The merge function — the architectural heart of ARIA.

The brief says ARIA must remember every person it has ever spoken with and open the
next call with a brief summary. We do not interpret this as "store the last
transcript and read it back." We interpret it as: maintain a per-caller PROFILE
that ACCUMULATES across calls, and regenerate the running summary from that
profile every time.

Each post-call extraction returns the same field shape. Merge rules per field:

  - REPLACE_NEWEST   one canonical value, newest non-empty wins. Old value moved
                     to a `history` list with a timestamp. Used for fields that
                     change over time (current_role, current_focus).

  - UNION_LIST       set-union of the lists, deduplicated case-insensitively,
                     order-preserving. Used for fields that GROW (example_clients,
                     verticals_they_work_in).

  - APPEND_UTTERANCE keep every utterance Claude extracted across calls in a list,
                     promote the longest non-empty one as canonical. Used for
                     positioning statements where the caller's phrasing matters.

  - LOCK_ON_FIRST    once written, never changed (the caller's name, basically).

The shape of the profile is intentionally JSON-blob-flat. Versioned schema is
"what I would add with more time" — see README.

Design intent: every merge is deterministic given (old_profile, new_extraction)
so it is unit-testable without a network call. Test in tests/test_merge.py.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Map of field name → merge rule. The structured extraction prompt produces
# exactly these keys; if you add a field you add it here too.
MERGE_RULES: dict[str, str] = {
    "name":                      "LOCK_ON_FIRST",
    "current_role":              "REPLACE_NEWEST",
    "company":                   "REPLACE_NEWEST",
    "what_they_built":           "APPEND_UTTERANCE",
    "biggest_client_result":     "APPEND_UTTERANCE",
    "who_they_typically_work_with": "APPEND_UTTERANCE",
    "example_clients":           "UNION_LIST",
    "verticals":                 "UNION_LIST",
    "tone_notes":                "UNION_LIST",
    "free_text_summary":         "APPEND_UTTERANCE",
}


def _normalize_str(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip()


def _is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    if isinstance(v, (list, dict)) and not v:
        return True
    return False


def _dedup_preserve_order_ci(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        s = _normalize_str(item)
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def merge_profile(
    existing_profile: dict[str, Any] | None,
    new_extraction: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """
    Pure function. Returns a NEW dict, does not mutate inputs.

    `existing_profile` is what is currently in the DB (may be {} for first call).
    `new_extraction` is the structured Claude output for the current call.
    """
    profile = copy.deepcopy(existing_profile or {})
    now = now or utcnow_iso()

    for field, rule in MERGE_RULES.items():
        new_value = new_extraction.get(field)

        if rule == "LOCK_ON_FIRST":
            if _is_empty(profile.get(field)) and not _is_empty(new_value):
                profile[field] = _normalize_str(new_value)

        elif rule == "REPLACE_NEWEST":
            if _is_empty(new_value):
                continue
            old = profile.get(field)
            if old and _normalize_str(old) != _normalize_str(new_value):
                history = profile.setdefault(f"{field}_history", [])
                history.append({"value": _normalize_str(old), "replaced_at": now})
            profile[field] = _normalize_str(new_value)

        elif rule == "UNION_LIST":
            if isinstance(new_value, list):
                incoming = [_normalize_str(x) for x in new_value if not _is_empty(x)]
            elif isinstance(new_value, str) and new_value.strip():
                incoming = [_normalize_str(new_value)]
            else:
                incoming = []
            if not incoming:
                continue
            old_list = profile.get(field, [])
            if not isinstance(old_list, list):
                old_list = [_normalize_str(old_list)]
            profile[field] = _dedup_preserve_order_ci(old_list + incoming)

        elif rule == "APPEND_UTTERANCE":
            if _is_empty(new_value):
                continue
            history_key = f"{field}_utterances"
            utterances = profile.get(history_key, [])
            if not isinstance(utterances, list):
                utterances = []
            utterances.append({"value": _normalize_str(new_value), "captured_at": now})
            profile[history_key] = utterances
            best = max(utterances, key=lambda u: len(u.get("value", "")))
            profile[field] = best["value"]

    profile["_last_merged_at"] = now
    profile["_merge_count"] = profile.get("_merge_count", 0) + 1
    return profile


def render_profile_for_prompt(profile: dict[str, Any]) -> str:
    """
    Compact, prompt-friendly rendering of the profile for the returning-caller
    opener. We strip housekeeping fields and `_history` / `_utterances` lists.
    The opener prompt does not need the full audit trail; it needs the canonical
    values. The full profile stays in the DB.
    """
    if not profile:
        return "(empty profile — first call)"
    keep = {}
    for k, v in profile.items():
        if k.startswith("_"):
            continue
        if k.endswith("_history") or k.endswith("_utterances"):
            continue
        if _is_empty(v):
            continue
        keep[k] = v
    if not keep:
        return "(empty profile — first call)"
    lines = []
    for k, v in keep.items():
        if isinstance(v, list):
            lines.append(f"- {k}: {', '.join(v)}")
        else:
            lines.append(f"- {k}: {v}")
    return "\n".join(lines)
