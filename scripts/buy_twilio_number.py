"""
Buy a Twilio number for ARIA.

Usage:
    python scripts/buy_twilio_number.py --search                  # list 5 US local
    python scripts/buy_twilio_number.py --search --country PL --kind mobile
    python scripts/buy_twilio_number.py --buy +1XXXXXXXXXX
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()


def load_twilio_creds() -> tuple[str, str]:
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        print("ERROR: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set in .env")
        sys.exit(1)
    return sid, token


def search(client: Client, area_code: str | None = None, limit: int = 5, country: str = "US", kind: str = "local"):
    kwargs = {"voice_enabled": True, "limit": limit}
    if area_code:
        kwargs["area_code"] = area_code
    avail = client.available_phone_numbers(country)
    pool = getattr(avail, kind)
    nums = pool.list(**kwargs)
    if not nums:
        print(f"No {country}/{kind} numbers available with those filters.")
        return []
    print(f"\nFound {len(nums)} {country} {kind} numbers:\n")
    for i, n in enumerate(nums, 1):
        loc = getattr(n, "locality", "") or ""
        reg = getattr(n, "region", "") or ""
        print(f"  {i}. {n.phone_number}  ({loc}, {reg})  voice={n.capabilities.get('voice')}")
    print()
    return nums


def buy(client: Client, phone_e164: str, address_sid: str | None = None, bundle_sid: str | None = None):
    print(f"Purchasing {phone_e164} ...")
    kwargs = {
        "phone_number": phone_e164,
        "friendly_name": "ARIA — BrandMultiplier discovery test",
    }
    if address_sid:
        kwargs["address_sid"] = address_sid
    if bundle_sid:
        kwargs["bundle_sid"] = bundle_sid
    purchased = client.incoming_phone_numbers.create(**kwargs)
    print(f"  OK. SID = {purchased.sid}")
    print(f"  Phone = {purchased.phone_number}")
    return purchased


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--search", action="store_true", help="list candidate numbers, do NOT buy")
    p.add_argument("--buy", type=str, default=None, help="E.164 number to purchase")
    p.add_argument("--area-code", type=str, default=None)
    p.add_argument("--country", type=str, default="US", help="ISO country code (US, PL, ...)")
    p.add_argument("--kind", type=str, default="local", help="local | mobile | tollFree")
    p.add_argument("--address-sid", type=str, default=None, help="Twilio AddressSid (regulated countries)")
    p.add_argument("--bundle-sid", type=str, default=None, help="Twilio BundleSid (regulated countries)")
    args = p.parse_args()

    sid, token = load_twilio_creds()
    client = Client(sid, token)

    if args.search:
        search(client, area_code=args.area_code, limit=5, country=args.country, kind=args.kind)
    elif args.buy:
        buy(client, args.buy, address_sid=args.address_sid, bundle_sid=args.bundle_sid)
    else:
        search(client, area_code=args.area_code, limit=5, country=args.country, kind=args.kind)
        print("Re-run with --buy <number> to purchase.")
