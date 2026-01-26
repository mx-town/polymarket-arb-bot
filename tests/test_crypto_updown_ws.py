#!/usr/bin/env python3
"""
Test WebSocket with actual BTC/ETH updown markets.
Verifies we receive price_change events for these specific markets.
"""

import json
import time
import threading
import requests
import websocket

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


def fetch_updown_markets(limit=20):
    """Fetch btc-updown and eth-updown markets"""
    print("Fetching crypto updown markets...")
    
    all_markets = []
    offset = 0
    
    while len(all_markets) < limit:
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
        
        for m in markets:
            clob_tokens = parse_json_field(m.get("clobTokenIds"))
            if len(clob_tokens) != 2:
                continue
            
            slug = m.get("slug", "").lower()
            question = m.get("question", "").lower()
            
            # Filter for btc-updown or eth-updown
            if "btc-updown" in slug or "eth-updown" in slug:
                all_markets.append({
                    "slug": m.get("slug"),
                    "question": m.get("question"),
                    "token_yes": clob_tokens[0],
                    "token_no": clob_tokens[1],
                })
                if len(all_markets) >= limit:
                    break
        
        offset += 100
        if len(markets) < 100:
            break
    
    print(f"Found {len(all_markets)} updown markets")
    return all_markets


def main():
    print("="*60)
    print("CRYPTO UPDOWN WEBSOCKET TEST")
    print("="*60)
    
    # Fetch markets
    markets = fetch_updown_markets(limit=10)
    
    if not markets:
        print("No btc-updown or eth-updown markets found!")
        return
    
    # Collect all token IDs
    token_ids = []
    token_to_market = {}
    
    for m in markets:
        print(f"\n  Market: {m['slug'][:50]}...")
        print(f"    Token YES: {m['token_yes'][:30]}...")
        print(f"    Token NO:  {m['token_no'][:30]}...")
        token_ids.append(m['token_yes'])
        token_ids.append(m['token_no'])
        token_to_market[m['token_yes']] = m['slug']
        token_to_market[m['token_no']] = m['slug']
    
    print(f"\nTotal tokens to subscribe: {len(token_ids)}")
    
    # Track received events
    received_events = []
    price_changes_for_our_tokens = []
    
    ws_instance = None
    
    def on_message(ws, message):
        nonlocal price_changes_for_our_tokens
        
        if isinstance(message, bytes) or not message.startswith('{'):
            return
        
        try:
            data = json.loads(message)
            if not isinstance(data, dict):
                return
            
            event_type = data.get("event_type")
            
            if event_type == "price_change":
                changes = data.get("price_changes", [])
                for change in changes:
                    if isinstance(change, dict):
                        asset_id = change.get("asset_id")
                        if asset_id in token_to_market:
                            price_changes_for_our_tokens.append({
                                "asset_id": asset_id[:30],
                                "market": token_to_market[asset_id][:30],
                                "best_bid": change.get("best_bid"),
                                "best_ask": change.get("best_ask"),
                            })
                            print(f"\n[PRICE_CHANGE] Market: {token_to_market[asset_id][:40]}")
                            print(f"  bid={change.get('best_bid')} ask={change.get('best_ask')}")
            
            elif event_type == "book":
                asset_id = data.get("asset_id")
                if asset_id in token_to_market:
                    bids = data.get("bids", [])
                    asks = data.get("asks", [])
                    if bids and asks:
                        print(f"\n[BOOK] Market: {token_to_market[asset_id][:40]}")
                        print(f"  best_bid={bids[0][0] if bids else 'N/A'} best_ask={asks[0][0] if asks else 'N/A'}")
                    
        except Exception as e:
            print(f"[ERROR] {e}")
    
    def on_open(ws):
        nonlocal ws_instance
        ws_instance = ws
        print("\n[CONNECTED]")
        
        msg = {"type": "market", "assets_ids": token_ids}
        ws.send(json.dumps(msg))
        print(f"[SUBSCRIBED] to {len(token_ids)} tokens")
    
    def on_error(ws, error):
        print(f"[ERROR] {error}")
    
    def on_close(ws, code, msg):
        print(f"[CLOSED] code={code}")
    
    ws = websocket.WebSocketApp(
        POLYMARKET_WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    
    def ping_loop():
        while True:
            try:
                time.sleep(5)
                if ws_instance:
                    ws_instance.send("ping")
            except:
                break
    
    # Run WebSocket
    ws_thread = threading.Thread(target=lambda: ws.run_forever(), daemon=True)
    ws_thread.start()
    
    time.sleep(2)
    
    ping_thread = threading.Thread(target=ping_loop, daemon=True)
    ping_thread.start()
    
    # Wait for events
    print("\nWaiting 60 seconds for price updates...")
    try:
        time.sleep(60)
    except KeyboardInterrupt:
        pass
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Price changes received for our tokens: {len(price_changes_for_our_tokens)}")
    
    if price_changes_for_our_tokens:
        print("\nSample price changes:")
        for pc in price_changes_for_our_tokens[:5]:
            print(f"  - {pc['market']}: bid={pc['best_bid']} ask={pc['best_ask']}")
        print("\nSUCCESS: WebSocket is receiving price updates for crypto updown markets!")
    else:
        print("\nWARNING: No price_change events received for our subscribed tokens.")
        print("This could mean:")
        print("  1. These markets have low activity")
        print("  2. The markets are closed/expired")
        print("  3. There's a subscription issue")
    
    ws.close()


if __name__ == "__main__":
    main()
