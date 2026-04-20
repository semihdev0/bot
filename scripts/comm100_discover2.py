"""Comm100 API - try different OAuth formats to find the correct one."""

from __future__ import annotations

import asyncio
import json
import os
import sys

import aiohttp
from dotenv import load_dotenv


async def main() -> None:
    load_dotenv()

    email = os.environ.get("COMM100_EMAIL", "")
    password = os.environ.get("COMM100_PASSWORD", "")
    site_id = os.environ.get("COMM100_SITE_ID", "")

    if not all([email, password, site_id]):
        print("HATA: .env ayarla")
        sys.exit(1)

    # Responsive endpoints from first test
    bases = [
        "https://api15.comm100.io",
        "https://dash15.comm100.io",
        "https://api15.lively-chat.com",
        "https://dash15.lively-chat.com",
        "https://api11.comm100.io",
    ]

    # Different payload formats to try
    payloads = [
        ("form: grant_type+email+password+siteId", {
            "grant_type": "password",
            "email": email,
            "password": password,
            "siteId": site_id,
        }, "form"),
        ("form: grant_type+email+password (no siteId)", {
            "grant_type": "password",
            "email": email,
            "password": password,
        }, "form"),
        ("form: grant_type+username+password+siteId", {
            "grant_type": "password",
            "username": email,
            "password": password,
            "siteId": site_id,
        }, "form"),
        ("json: grant_type+email+password+siteId", {
            "grant_type": "password",
            "email": email,
            "password": password,
            "siteId": int(site_id),
        }, "json"),
        ("form: client_credentials", {
            "grant_type": "client_credentials",
            "siteId": site_id,
            "email": email,
            "password": password,
        }, "form"),
    ]

    print("=" * 60)
    print(f"Email: {email} | Site ID: {site_id}")
    print("=" * 60)

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=15)
    ) as session:

        for base in bases:
            token_url = f"{base}/oauth/token"
            print(f"\n--- {token_url} ---")

            for label, payload, mode in payloads:
                try:
                    if mode == "json":
                        async with session.post(
                            token_url, json=payload
                        ) as resp:
                            status = resp.status
                            body = await resp.text()
                    else:
                        async with session.post(
                            token_url, data=payload
                        ) as resp:
                            status = resp.status
                            body = await resp.text()

                    if status == 200 and "access_token" in body:
                        print(f"  [BASARILI] {label}")
                        print(f"  Token: {body[:100]}...")
                        print(f"\n  CALISAN URL: {base}")
                        return
                    else:
                        # Show just the error
                        try:
                            err = json.loads(body)
                            err_msg = err.get("error", err.get("message", body[:80]))
                            err_desc = err.get("error_description", "")
                            print(f"  [{status}] {label} -> {err_msg} {err_desc}")
                        except:
                            print(f"  [{status}] {label} -> {body[:80]}")

                except Exception as e:
                    print(f"  [ERR] {label} -> {e}")

        # Try Basic Auth as fallback
        print("\n\n--- Basic Auth Test ---")
        for base in bases[:2]:
            auth = aiohttp.BasicAuth(email, password)
            url = f"{base}/api/v4/global/agents"
            try:
                async with session.get(
                    url, auth=auth,
                    headers={"x-api-siteid": site_id}
                ) as resp:
                    status = resp.status
                    body = await resp.text()
                    print(f"  [{status}] {base} BasicAuth -> {body[:100]}")
            except Exception as e:
                print(f"  [ERR] {base} BasicAuth -> {e}")

        print("\n" + "=" * 60)
        print("Hicbir yontem calismadi.")


if __name__ == "__main__":
    asyncio.run(main())
