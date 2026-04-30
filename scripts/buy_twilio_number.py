"""
Buy a US local Twilio number for ARIA.

Usage:
    python scripts/buy_twilio_number.py --search       # list 5 candidates, do NOT buy
    python scripts/buy_twilio_number.py --buy <PHONE>  # buy a specific number from the candidates

Reuses Twilio creds from D:\\Python\\sms_dla_warsztat\\V13_final_touch\\.env
(same Twilio account billing as existing infra).
"""

import argparse
import os
import sys
from pathlib import Path

from twilio.rest import Client

V13_ENV = Path(r"D:\Python\sms_dla_warsztat\V13_final_touch\.env")


def load_twilio_creds() -> tuple[str, str]:
    sid = None
    token = None
    if V13_ENV.exists():
        for line in V13_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("TWILIO_ACCOUNT_SID="):
                sid = line.split("=", 1)[1].strip()
            elif line.startswith("TWILIO_AUTH_TOKEN="):
                token = line.split("=", 1)[1].strip()
    sid = sid or os.getenv("TWILIO_ACCOUNT_SID")
    token = token or os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        print("ERROR: missing Twilio creds")
        sys.exit(1)
    return sid, token


def search(client: Client, area_code: str | None = None, limit: int = 5):
    kwargs = {"voice_enabled": True, "limit": limit}
    if area_code:
        kwargs["area_code"] = area_code
    nums = client.available_phone_numbers("US").local.list(**kwargs)
    if not nums:
        print("No numbers available with those filters.")
        return []
    print(f"\nFound {len(nums)} US local numbers:\n")
    for i, n in enumerate(nums, 1):
        print(f"  {i}. {n.phone_number}  ({n.locality}, {n.region})  voice={n.capabilities.get('voice')}")
    print()
    return nums


def buy(client: Client, phone_e164: str):
    print(f"Purchasing {phone_e164} ...")
    purchased = client.incoming_phone_numbers.create(
        phone_number=phone_e164,
        friendly_name="ARIA — BrandMultiplier discovery test",
    )
    print(f"  OK. SID = {purchased.sid}")
    print(f"  Phone = {purchased.phone_number}")
    print(f"\nNext step: configure voice webhook on this number to point at your ngrok URL.")
    return purchased


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--search", action="store_true", help="list candidate numbers, do NOT buy")
    p.add_argument("--buy", type=str, default=None, help="E.164 number to purchase")
    p.add_argument("--area-code", type=str, default=None, help="optional 3-digit US area code filter")
    args = p.parse_args()

    sid, token = load_twilio_creds()
    client = Client(sid, token)

    if args.search:
        search(client, area_code=args.area_code, limit=5)
    elif args.buy:
        buy(client, args.buy)
    else:
        # default: list, then NOTHING. Explicit buy required.
        search(client, area_code=args.area_code, limit=5)
        print("Re-run with --buy <number> to purchase.")
