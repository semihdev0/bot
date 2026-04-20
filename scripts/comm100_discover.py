"""Comm100 API endpoint discovery and authentication test.

Tries multiple possible API base URLs to find the correct one
for your Comm100/Lively Chat account.

Usage: python scripts/comm100_discover.py
"""

from __future__ import annotations

import asyncio
import os
import sys

import aiohttp
from dotenv import load_dotenv

CANDIDATE_TOKEN_URLS = [
    "https://api15.comm100.io/oauth/token",
    "https://dash15.comm100.io/oauth/token",
    "https://portal15.comm100.io/oauth/token",
    "https://secure.comm100.io/oauth/token",
    "https://api15.lively-chat.com/oauth/token",
    "https://dash15.lively-chat.com/oauth/token",
    "https://api1.comm100.io/oauth/token",
    "https://api2.comm100.io/oauth/token",
    "https://api3.comm100.io/oauth/token",
    "https://api5.comm100.io/oauth/token",
    "https://api7.comm100.io/oauth/token",
    "https://api11.comm100.io/oauth/token",
]


async def main() -> None:
    load_dotenv()

    email = os.environ.get("COMM100_EMAIL", "")
    password = os.environ.get("COMM100_PASSWORD", "")
    site_id = os.environ.get("COMM100_SITE_ID", "")

    if not all([email, password, site_id]):
        print("HATA: .env dosyasinda COMM100_EMAIL, COMM100_PASSWORD, COMM100_SITE_ID ayarla")
        sys.exit(1)

    payload = {
        "grant_type": "password",
        "email": email,
        "password": password,
        "siteId": site_id,
    }

    print("=" * 60)
    print("Comm100 API Baglanti Testi")
    print(f"  Email: {email}")
    print(f"  Site ID: {site_id}")
    print("=" * 60)

    access_token = None
    working_base = None

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=15)
    ) as session:

        # Step 1: Find working OAuth endpoint
        print("\n1. OAuth Token Endpoint Araniyor...\n")
        for url in CANDIDATE_TOKEN_URLS:
            try:
                async with session.post(url, data=payload) as resp:
                    status = resp.status
                    if status == 200:
                        data = await resp.json()
                        if "access_token" in data:
                            access_token = data["access_token"]
                            working_base = url.replace("/oauth/token", "")
                            expires = data.get("expires_in", "?")
                            print(f"   [BASARILI] {url}")
                            print(f"              Token alindi! (expires_in: {expires}s)")
                            break
                        else:
                            print(f"   [YANLIS]   {url} -> {status} (token yok)")
                    elif status in (400, 401):
                        body = await resp.text()
                        print(f"   [KIMLIK]   {url} -> {status}: {body[:80]}")
                    else:
                        body = await resp.text()
                        print(f"   [HATA]     {url} -> {status}: {body[:80]}")
            except aiohttp.ClientConnectorError:
                print(f"   [ERISIM X] {url} -> Baglanilamiyor")
            except asyncio.TimeoutError:
                print(f"   [ZAMAN]    {url} -> Zaman asimi")
            except Exception as e:
                print(f"   [HATA]     {url} -> {e}")

        if not access_token:
            print("\n" + "=" * 60)
            print("BASARISIZ: Hicbir endpoint'ten token alinamadi.")
            print("Kontrol et:")
            print("  1. Email ve sifre dogru mu?")
            print("  2. Site ID dogru mu?")
            print("  3. Internet baglantisi var mi?")
            print("=" * 60)
            sys.exit(1)

        # Step 2: Test API endpoints
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "x-api-siteid": site_id,
        }

        print(f"\n2. API Endpoint'leri Test Ediliyor (Base: {working_base})...\n")

        api_paths = [
            ("v4/global/agents", "Agents"),
            ("v4/global/departments", "Departments"),
            ("v4/livechat/chats", "Active Chats"),
            ("v4/livechat/campaigns", "Campaigns"),
            ("v3/livechat/chats", "Chats (v3)"),
        ]

        for path, label in api_paths:
            url = f"{working_base}/api/{path}"
            try:
                async with session.get(url, headers=headers) as resp:
                    status = resp.status
                    if status == 200:
                        data = await resp.json()
                        count = len(data) if isinstance(data, list) else "OK"
                        print(f"   [OK]  {label}: {count} - {url}")
                    else:
                        body = await resp.text()
                        print(f"   [ERR] {label}: {status} - {url} - {body[:80]}")
            except Exception as e:
                print(f"   [ERR] {label}: {url} - {e}")

        # Step 3: Summary
        print("\n" + "=" * 60)
        print("SONUC")
        print(f"  Calisan API Base URL: {working_base}")
        print(f"\n  .env dosyana su satiri ekle/guncelle:")
        print(f"  COMM100_API_BASE_URL={working_base}")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
