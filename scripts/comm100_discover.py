"""Comm100 API endpoint discovery and authentication test.

Usage: python scripts/comm100_discover.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import aiohttp
from dotenv import load_dotenv


async def main() -> None:
    load_dotenv()

    email = os.environ.get("COMM100_EMAIL", "")
    api_key = os.environ.get("COMM100_API_KEY", "")
    site_id = os.environ.get("COMM100_SITE_ID", "")
    region = os.environ.get("COMM100_REGION", "1")

    if not all([email, api_key, site_id]):
        print("ERROR: Set COMM100_EMAIL, COMM100_API_KEY, COMM100_SITE_ID in .env")
        sys.exit(1)

    base_v4 = f"https://api{region}.comm100.io/api/v4"
    auth = aiohttp.BasicAuth(email, api_key)
    headers = {"x-api-siteid": site_id}

    endpoints = [
        ("GET", f"{base_v4}/global/agents", "Agents"),
        ("GET", f"{base_v4}/global/departments", "Departments"),
        ("GET", f"{base_v4}/livechat/chats", "Active Chats"),
        ("GET", f"{base_v4}/livechat/campaigns", "Campaigns"),
    ]

    async with aiohttp.ClientSession(auth=auth, headers=headers) as session:
        print(f"Testing Comm100 API (region={region}, site={site_id})")
        print(f"Email: {email}")
        print("-" * 60)

        for method, url, label in endpoints:
            try:
                async with session.request(method, url) as resp:
                    status = resp.status
                    if status == 200:
                        data = await resp.json()
                        count = len(data) if isinstance(data, list) else "OK"
                        print(f"  [OK]  {label}: {status} ({count})")
                    else:
                        body = await resp.text()
                        print(f"  [ERR] {label}: {status} - {body[:100]}")
            except Exception as e:
                print(f"  [ERR] {label}: {e}")

        print("-" * 60)
        print("Discovery complete.")


if __name__ == "__main__":
    asyncio.run(main())
