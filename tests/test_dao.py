"""DAO + phone normalization."""

import pytest

from aria.db.dao import normalize_e164, get_caller, upsert_caller, insert_conversation, get_conversation


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+18005550100", "+18005550100"),
        ("18005550100", "+18005550100"),
        ("+1 (800) 555-0100", "+18005550100"),
        ("  +1 800 555 0100  ", "+18005550100"),
        ("", ""),
        (None, ""),  # defensive
    ],
)
def test_normalize_e164(raw, expected):
    assert normalize_e164(raw) == expected


@pytest.mark.asyncio
async def test_upsert_inserts_and_updates():
    phone = "+15551234567"
    c1 = await upsert_caller(phone, name="Alice")
    assert c1.name == "Alice"
    assert c1.call_count == 0
    assert c1.is_returning is False

    c2 = await upsert_caller(phone, profile={"company": "Acme"}, summary="hello", bump_call_count=True)
    assert c2.name == "Alice"  # untouched
    assert c2.profile == {"company": "Acme"}
    assert c2.summary == "hello"
    assert c2.call_count == 1
    assert c2.is_returning is True


@pytest.mark.asyncio
async def test_get_caller_returns_none_for_unknown():
    assert await get_caller("+15550000000") is None


@pytest.mark.asyncio
async def test_conversation_roundtrip():
    phone = "+15551234567"
    await upsert_caller(phone)
    await insert_conversation(conversation_id="CA_test_1", phone_e164=phone, is_returning_caller=False)
    row = await get_conversation("CA_test_1")
    assert row is not None
    assert row["phone_e164"] == phone
    assert row["is_returning_caller"] in (0, False)
