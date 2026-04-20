"""One-time interactive script to authenticate the Telegram account.

Run: python scripts/auth_telegram.py

This will prompt for the OTP code sent to your phone and create a session file
in the sessions/ directory. After this, the poster can run without interaction.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from pyrogram import Client

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"


async def main() -> None:
    load_dotenv()

    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    phone = os.environ["TELEGRAM_PHONE"]

    SESSIONS_DIR.mkdir(exist_ok=True)
    session_path = str(SESSIONS_DIR / "poster_account")

    print(f"Authenticating with phone: {phone}")
    print("You will receive an OTP code on Telegram...")

    client = Client(
        name=session_path,
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone,
    )

    await client.start()
    me = await client.get_me()
    print(f"Authenticated as: {me.first_name} (@{me.username})")
    print(f"Session saved to: {session_path}.session")
    await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
