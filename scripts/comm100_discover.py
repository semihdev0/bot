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
    password = os.environ.get("COMM100_PASSWORD", "")
    site_id = os.environ.get("COMM100_SITE_ID", "")
    api_base = os.environ.get("COMM100_API_BASE_URL", "https://api15.lively-chat.com")

    if not all([email, password, site_id]):
        print("ERROR: Set COMM100_EMAIL, COMM100_PASSWORD, COMM100_SITE_ID in .env")
        sys.exit(1)

    token_url = f"{api_base}/oauth/token"

    async with aiohttp.ClientSession() as session:
        print(f"Testing Comm100 API")
        print(f"  Base URL: {api_base}")
        print(f"  Email: {email}")
        print(f"  Site ID: {site_id}")
        print("-" * 60)

        # Step 1: Get OAuth token
        print("\n1. OAuth Authentication...")
        token_payload = {
            "grant_type": "password",
            "email": email,
            "password": password,
            "siteId": site_id,
        }
        access_token = None
        try:
            async with session.post(token_url, data=token_payload) as resp:
                status = resp.status
                body = await resp.json() if resp.content_type == "application/json" else {"raw": await resp.text()}
                if status == 200 and "access_token" in body:
                    access_token = body["access_token"]
                    expires = body.get("expires_in", "?")
                    print(f"   [OK] Token alindi (expires_in: {expires}s)")
                else:
                    print(f"   [ERR] {status}: {body}")
                    sys.exit(1)
        except Exception as e:
            print(f"   [ERR] {e}")

            # Try alternative token URLs
            alt_urls = [
                f"https://portal15.lively-chat.com/oauth/token",
                f"https://dash15.lively-chat.com/oauth/token",
                f"https://api15.comm100.io/oauth/token",
            ]
            for alt in alt_urls:
                print(f"\n   Trying: {alt}")
                try:
                    async with session.post(alt, data=token_payload) as resp:
                        status = resp.status
                        if status == 200:
                            body = await resp.json()
                            if "access_token" in body:
                                access_token = body["access_token"]
                                print(f"   [OK] Token alindi! Use this base URL.")
                                api_base = alt.replace("/oauth/token", "")
                                break
                        else:
                            body_text = await resp.text()
                            print(f"   [ERR] {status}: {body_text[:100]}")
                except Exception as e2:
                    print(f"   [ERR] {e2}")

        if not access_token:
            print("\nFailed to authenticate. Check credentials.")
            sys.exit(1)

        # Step 2: Test endpoints
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "x-api-siteid": site_id,
        }

        endpoints = [
            ("GET", f"{api_base}/api/v4/global/agents", "Agents"),
            ("GET", f"{api_base}/api/v4/global/departments", "Departments"),
            ("GET", f"{api_base}/api/v4/livechat/chats", "Active Chats"),
            ("GET", f"{api_base}/api/v4/livechat/campaigns", "Campaigns"),
            ("GET", f"{api_base}/api/v3/livechat/chats", "Chats (v3)"),
        ]

        print(f"\n2. Testing API Endpoints...")
        for method, url, label in endpoints:
            try:
                async with session.request(method, url, headers=headers) as resp:
                    status = resp.status
                    if status == 200:
                        data = await resp.json()
                        count = len(data) if isinstance(data, list) else "OK"
                        print(f"   [OK]  {label}: {status} ({count})")
                    else:
                        body = await resp.text()
                        print(f"   [ERR] {label}: {status} - {body[:100]}")
            except Exception as e:
                print(f"   [ERR] {label}: {e}")

        print("-" * 60)
        print("Discovery complete.")
        if access_token:
            print(f"\nWorking API Base URL: {api_base}")
            print("Set COMM100_API_BASE_URL in .env to this value.")


if __name__ == "__main__":
    asyncio.run(main())
