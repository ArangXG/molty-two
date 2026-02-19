#!/usr/bin/env python3
"""
Debug tool — print RAW API responses untuk diagnose format.
Run: python3 debug_api.py
"""
import asyncio, aiohttp, json, os, sys

API_BASE = os.getenv("MOLTY_API_BASE", "https://www.moltyroyale.com/api")
API_KEY  = os.getenv("MOLTY_API_KEY",  "YOUR_API_KEY_HERE")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type":  "application/json",
}

ENDPOINTS_TO_TRY = [
    ("GET", "/rooms"),
    ("GET", "/room"),
    ("GET", "/lobby"),
    ("GET", "/lobby/rooms"),
    ("GET", "/api/rooms"),
    ("GET", "/v1/rooms"),
    ("GET", "/game/rooms"),
    ("GET", "/matchmaking/rooms"),
]

async def probe():
    print("=" * 60)
    print(f"  API BASE : {API_BASE}")
    print(f"  API KEY  : {API_KEY[:8]}..." if len(API_KEY) > 8 else f"  API KEY  : {API_KEY}")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        for method, path in ENDPOINTS_TO_TRY:
            url = f"{API_BASE}{path}"
            print(f"\n{'─'*50}")
            print(f"  {method} {url}")
            try:
                async with session.request(
                    method, url, headers=HEADERS,
                    timeout=aiohttp.ClientTimeout(total=6)
                ) as r:
                    body = await r.text()
                    print(f"  Status : {r.status}")
                    print(f"  Headers: {dict(r.headers)}")
                    print(f"  Body   : {body[:500]}")
                    if r.status == 200:
                        print(f"  ✅ FOUND WORKING ENDPOINT: {path}")
                        try:
                            parsed = json.loads(body)
                            print(f"  Parsed type : {type(parsed)}")
                            if isinstance(parsed, dict):
                                print(f"  Dict keys   : {list(parsed.keys())}")
                            elif isinstance(parsed, list) and parsed:
                                print(f"  List[0] type: {type(parsed[0])}")
                                print(f"  List[0]     : {parsed[0]}")
                        except:
                            pass
            except aiohttp.ClientConnectorError as e:
                print(f"  ❌ Cannot connect: {e}")
            except asyncio.TimeoutError:
                print(f"  ⏱ Timeout")
            except Exception as e:
                print(f"  ❌ Error: {e}")

asyncio.run(probe())
