#!/usr/bin/env python3
"""
Test script to inspect Polymarket REST API responses.
"""

import json
import requests

def main():
    print("="*60)
    print("POLYMARKET REST API TEST")
    print("="*60)
    
    # Get a few active markets
    print("\nFetching markets...")
    resp = requests.get(
        "https://gamma-api.polymarket.com/markets",
        params={
            "closed": "false",
            "archived": "false", 
            "limit": 3,
        }
    )
    
    markets = resp.json()
    print(f"Got {len(markets)} markets\n")
    
    for i, market in enumerate(markets):
        print(f"\n{'='*60}")
        print(f"MARKET {i+1}")
        print(f"{'='*60}")
        print(f"Question: {market.get('question', '?')[:80]}")
        print(f"Condition ID: {market.get('conditionId', '?')}")
        print(f"Slug: {market.get('slug', '?')}")
        
        # Check clobTokenIds
        clob_tokens = market.get("clobTokenIds")
        print(f"\nclobTokenIds type: {type(clob_tokens)}")
        print(f"clobTokenIds value: {clob_tokens}")
        
        # If it's a string, try parsing it
        if isinstance(clob_tokens, str):
            try:
                parsed = json.loads(clob_tokens)
                print(f"Parsed clobTokenIds: {parsed}")
                print(f"Parsed type: {type(parsed)}")
            except:
                print("Failed to parse as JSON")
        
        # Check outcomes and tokens structure
        outcomes = market.get("outcomes")
        print(f"\noutcomes: {outcomes}")
        
        tokens = market.get("tokens")
        print(f"\ntokens type: {type(tokens)}")
        if tokens:
            print(f"tokens[0] keys: {list(tokens[0].keys()) if isinstance(tokens[0], dict) else tokens[0]}")
            for j, token in enumerate(tokens[:2]):
                if isinstance(token, dict):
                    print(f"  Token {j}: token_id={token.get('token_id', '?')[:30]}...")
                    print(f"           outcome={token.get('outcome', '?')}")
        
        # Print all keys for reference
        print(f"\nAll market keys: {list(market.keys())}")


if __name__ == "__main__":
    main()
