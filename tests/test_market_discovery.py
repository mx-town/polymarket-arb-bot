#!/usr/bin/env python3
"""
Test market discovery - check what markets match the bot's filters.
"""

import json
import requests

def parse_json_field(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except:
            return []
    return []


def main():
    print("="*60)
    print("MARKET DISCOVERY TEST")
    print("="*60)
    
    # Fetch all markets
    print("\nFetching all active markets...")
    all_markets = []
    offset = 0
    
    while True:
        resp = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={
                "closed": "false",
                "archived": "false",
                "limit": 100,
                "offset": offset,
            },
            timeout=15,
        )
        markets = resp.json()
        if not markets:
            break
        all_markets.extend(markets)
        if len(markets) < 100:
            break
        offset += 100
        print(f"  Fetched {len(all_markets)} markets so far...")
    
    print(f"\nTotal markets fetched: {len(all_markets)}")
    
    # Filter for binary markets (2 tokens)
    binary_markets = []
    for m in all_markets:
        clob_tokens = parse_json_field(m.get("clobTokenIds"))
        if len(clob_tokens) == 2:
            binary_markets.append(m)
    
    print(f"Binary markets (2 tokens): {len(binary_markets)}")
    
    # Search for Up/Down market patterns
    market_types = ["btc-updown", "eth-updown", "up-or-down", "btc", "eth", "bitcoin", "ethereum"]
    
    print(f"\n--- Searching for specific patterns ---")
    
    for pattern in market_types:
        matching = []
        for m in binary_markets:
            slug = m.get("slug", "").lower()
            question = m.get("question", "").lower()
            
            if pattern.lower() in slug or pattern.lower() in question:
                matching.append(m)
        
        print(f"\nPattern '{pattern}': {len(matching)} matches")
        for m in matching[:3]:
            print(f"  - {m.get('slug', '?')[:50]}...")
            print(f"    Question: {m.get('question', '?')[:60]}...")
    
    # Check for any crypto-related markets
    print("\n--- All markets with 'crypto' patterns ---")
    crypto_patterns = ["btc", "eth", "bitcoin", "ethereum", "crypto", "coin"]
    crypto_markets = []
    
    for m in binary_markets:
        slug = m.get("slug", "").lower()
        question = m.get("question", "").lower()
        
        for pattern in crypto_patterns:
            if pattern in slug or pattern in question:
                crypto_markets.append(m)
                break
    
    print(f"Found {len(crypto_markets)} crypto-related markets")
    for m in crypto_markets[:10]:
        print(f"  - {m.get('slug', '?')[:60]}")
        print(f"    Q: {m.get('question', '?')[:70]}...")


if __name__ == "__main__":
    main()
