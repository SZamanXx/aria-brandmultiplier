"""
Pure-function tests for the memory merge layer. These are the most important
tests because the merge layer is the architectural heart of ARIA.
"""

import copy

from aria.memory.merge import merge_profile, render_profile_for_prompt


def _empty():
    return {}


def test_lock_on_first_name_does_not_overwrite():
    p1 = merge_profile(_empty(), {"name": "Sapir"})
    assert p1["name"] == "Sapir"
    p2 = merge_profile(p1, {"name": "Different Name"})
    assert p2["name"] == "Sapir"  # locked


def test_lock_on_first_accepts_when_empty():
    p = merge_profile({"name": ""}, {"name": "Sapir"})
    assert p["name"] == "Sapir"


def test_replace_newest_writes_history():
    p1 = merge_profile(_empty(), {"current_role": "Founder"})
    p2 = merge_profile(p1, {"current_role": "CEO"})
    assert p2["current_role"] == "CEO"
    assert p2["current_role_history"][0]["value"] == "Founder"
    assert "replaced_at" in p2["current_role_history"][0]


def test_replace_newest_skips_when_same():
    p1 = merge_profile(_empty(), {"current_role": "CEO"})
    p2 = merge_profile(p1, {"current_role": "CEO"})
    assert p2["current_role"] == "CEO"
    assert "current_role_history" not in p2


def test_union_list_dedup_case_insensitive_preserves_order():
    p1 = merge_profile(_empty(), {"example_clients": ["Acme", "Globex"]})
    p2 = merge_profile(p1, {"example_clients": ["acme", "Initech"]})
    # acme is dedup of Acme (case-insensitive), Initech is new
    assert p2["example_clients"] == ["Acme", "Globex", "Initech"]


def test_union_list_accepts_string_input():
    p = merge_profile(_empty(), {"verticals": "SaaS"})
    assert p["verticals"] == ["SaaS"]


def test_append_utterance_promotes_longest_to_canonical():
    p1 = merge_profile(_empty(), {"biggest_client_result": "Tripled MRR."})
    p2 = merge_profile(p1, {"biggest_client_result": "Helped a SaaS founder triple MRR in one quarter through their referral network."})
    assert p2["biggest_client_result"].startswith("Helped a SaaS founder")
    assert len(p2["biggest_client_result_utterances"]) == 2


def test_append_utterance_keeps_history_in_order():
    p1 = merge_profile(_empty(), {"what_they_built": "AAA"})
    p2 = merge_profile(p1, {"what_they_built": "BBBB"})
    p3 = merge_profile(p2, {"what_they_built": "CC"})
    vals = [u["value"] for u in p3["what_they_built_utterances"]]
    assert vals == ["AAA", "BBBB", "CC"]
    assert p3["what_they_built"] == "BBBB"  # longest


def test_empty_extraction_is_idempotent_modulo_metadata():
    p1 = merge_profile(_empty(), {"name": "Alice", "current_role": "CTO"})
    p2 = merge_profile(p1, {})
    # Skip metadata bookkeeping fields when comparing payload.
    keys = lambda d: {k: d[k] for k in d if not k.startswith("_")}
    assert keys(p1) == keys(p2)
    assert p2["_merge_count"] == p1["_merge_count"] + 1


def test_merge_does_not_mutate_input():
    p_in = {"name": "Sapir", "example_clients": ["Acme"]}
    snapshot = copy.deepcopy(p_in)
    _ = merge_profile(p_in, {"example_clients": ["Globex"]})
    assert p_in == snapshot  # input untouched


def test_render_profile_strips_internal_fields():
    profile = {
        "name": "Sapir",
        "current_role": "Founder",
        "current_role_history": [{"value": "CTO", "replaced_at": "x"}],
        "biggest_client_result": "Tripled MRR.",
        "biggest_client_result_utterances": [{"value": "Tripled MRR.", "captured_at": "x"}],
        "_last_merged_at": "2026-04-30T00:00:00Z",
        "_merge_count": 3,
    }
    rendered = render_profile_for_prompt(profile)
    assert "Sapir" in rendered
    assert "Founder" in rendered
    assert "Tripled MRR." in rendered
    assert "_history" not in rendered
    assert "_utterances" not in rendered
    assert "_merge_count" not in rendered
    assert "replaced_at" not in rendered


def test_render_empty_profile():
    assert render_profile_for_prompt({}) == "(empty profile — first call)"
    assert render_profile_for_prompt({"_merge_count": 0}) == "(empty profile — first call)"
