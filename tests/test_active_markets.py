#!/usr/bin/env python3
"""
Find actively trading markets and test WebSocket with them.
"""

import json
import time
import threading
import requests
import websocket
from datetime import datetime

POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

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
    print("ACTIVE MARKETS TEST")
    print("="*60)
    
    # Fetch markets that are actively accepting orders with recent volume
    print("\nFetching active markets with recent volume...")
    
    resp = requests.get(
        "https://gamma-api.polymarket.com/markets",
        params={
            "closed": "false",
            "archived": "false",
            "limit": 50,
            "order": "volume24hr",
            "ascending": "false",
        },
        timeout=15,
    )
    markets = resp.json()
    
    print(f"Got {len(markets)} markets")
    
    # Filter for binary markets that are accepting orders
    active_markets = []
    crypto_updown_active = []
    
    for m in markets:
        clob_tokens = parse_json_field(m.get("clobTokenIds"))
        if len(clob_tokens) != 2:
            continue
        
        accepting = m.get("acceptingOrders", False)
        volume24h = m.get("volume24hr", 0)
        slug = m.get("slug", "").lower()
        
        market_info = {
            "slug": m.get("slug"),
            "question": m.get("question", "")[:60],
            "volume24hr": volume24h,
            "acceptingOrders": accepting,
            "token_yes": clob_tokens[0],
            "token_no": clob_tokens[1],
        }
        
        if accepting and volume24h > 0:
            active_markets.append(market_info)
            
            if "btc" in slug or "eth" in slug or "updown" in slug or "up-or-down" in slug:
                crypto_updown_active.append(market_info)
    
    print(f"\nActive markets (accepting orders + volume): {len(active_markets)}")
    print(f"Active crypto/updown markets: {len(crypto_updown_active)}")
    
    # Show top active markets
    print("\n--- Top 10 Active Markets by Volume ---")
    for m in active_markets[:10]:
        print(f"  ${m['volume24hr']:,.0f} | {m['slug'][:50]}")
        print(f"    Accepting: {m['acceptingOrders']}")
    
    # Show crypto updown markets if any
    if crypto_updown_active:
        print("\n--- Active Crypto/UpDown Markets ---")
        for m in crypto_updown_active[:10]:
            print(f"  ${m['volume24hr']:,.0f} | {m['slug'][:50]}")
    else:
        print("\n--- NO Active Crypto/UpDown Markets Found! ---")
        print("This explains why the bot isn't receiving price updates.")
    
    # Test with the most active markets
    if active_markets:
        print("\n--- Testing WebSocket with top 5 active markets ---")
        
        token_ids = []
        token_to_market = {}
        
        for m in active_markets[:5]:
            token_ids.append(m['token_yes'])
            token_ids.append(m['token_no'])
            token_to_market[m['token_yes']] = m['slug']
            token_to_market[m['token_no']] = m['slug']
        
        price_updates = []
        ws_instance = None
        
        def on_message(ws, message):
            if isinstance(message, bytes) or not message.startswith('{'):
                return
            try:
                data = json.loads(message)
                if isinstance(data, dict) and data.get("event_type") == "price_change":
                    changes = data.get("price_changes", [])
                    for change in changes:
                        if isinstance(change, dict):
                            asset_id = change.get("asset_id")
                            if asset_id in token_to_market:
                                price_updates.append({
                                    "market": token_to_market[asset_id][:30],
                                    "bid": change.get("best_bid"),
                                    "ask": change.get("best_ask"),
                                })
                                print(f"  [UPDATE] {token_to_market[asset_id][:40]}: bid={change.get('best_bid')} ask={change.get('best_ask')}")
            except:
                pass
        
        def on_open(ws):
            nonlocal ws_instance
            ws_instance = ws
            print("[CONNECTED]")
            ws.send(json.dumps({"type": "market", "assets_ids": token_ids}))
            print(f"[SUBSCRIBED] to {len(token_ids)} tokens")
        
        ws = websocket.WebSocketApp(
            POLYMARKET_WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=lambda ws, e: print(f"[ERROR] {e}"),
        )
        
        ws_thread = threading.Thread(target=lambda: ws.run_forever(), daemon=True)
        ws_thread.start()
        
        time.sleep(2)
        
        def ping_loop():
            while True:
                try:
                    time.sleep(5)
                    if ws_instance:
                        ws_instance.send("ping")
                except:
                    break
        
        ping_thread = threading.Thread(target=ping_loop, daemon=True)
        ping_thread.start()
        
        print("Waiting 30 seconds for updates...")
        time.sleep(30)
        
        print(f"\nReceived {len(price_updates)} price updates")
        ws.close()


if __name__ == "__main__":
    main()
