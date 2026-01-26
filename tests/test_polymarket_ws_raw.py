#!/usr/bin/env python3
"""
Test script to inspect raw Polymarket WebSocket messages.
This helps us understand the actual message format from the API.
"""

import json
import time
import websocket
import threading
import requests

POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Store received messages for analysis
received_messages = []
message_types = {}
ws_instance = None


def on_message(ws, message):
    """Capture and analyze messages"""
    global received_messages, message_types
    
    # Skip binary
    if isinstance(message, bytes):
        print(f"[BINARY] len={len(message)}")
        return
    
    # Skip empty
    if not message or not message.strip():
        return
    
    # Skip non-JSON
    if not message.startswith('{') and not message.startswith('['):
        if message not in ('PONG', 'pong'):
            print(f"[TEXT] {message[:50]}")
        return
    
    try:
        data = json.loads(message)
        
        # Handle list responses (subscription confirmations)
        if isinstance(data, list):
            print(f"[LIST RESPONSE] len={len(data)}")
            return
        
        if not isinstance(data, dict):
            print(f"[NON-DICT] type={type(data).__name__} value={data}")
            return
        
        event_type = data.get("event_type", "unknown")
        message_types[event_type] = message_types.get(event_type, 0) + 1
        
        # Store first few of each type for analysis
        if len([m for m in received_messages if m.get("event_type") == event_type]) < 3:
            received_messages.append(data)
            print(f"\n{'='*60}")
            print(f"EVENT TYPE: {event_type}")
            print(f"TOP-LEVEL KEYS: {list(data.keys())}")
            
            if event_type == "price_change":
                changes = data.get("price_changes", [])
                print(f"NUM CHANGES: {len(changes)}")
                if changes and isinstance(changes[0], dict):
                    print(f"CHANGE[0] KEYS: {list(changes[0].keys())}")
                    print(f"CHANGE[0] DATA: {json.dumps(changes[0], indent=2)}")
            
            elif event_type == "book":
                print(f"ASSET_ID: {data.get('asset_id', 'MISSING')[:30]}...")
                bids = data.get("bids", [])
                asks = data.get("asks", [])
                print(f"BIDS: {len(bids)} entries, first={bids[0] if bids else 'empty'}")
                print(f"ASKS: {len(asks)} entries, first={asks[0] if asks else 'empty'}")
            
            print(f"{'='*60}\n")
        else:
            count = message_types[event_type]
            if count % 10 == 0:
                print(f"[{event_type}] count: {count}")
            
    except json.JSONDecodeError as e:
        print(f"[PARSE ERROR] {e} - message: {message[:100]}")


def on_error(ws, error):
    print(f"[ERROR] {error}")


def on_close(ws, code, msg):
    print(f"[CLOSED] code={code} msg={msg}")


def on_open(ws):
    global ws_instance
    ws_instance = ws
    print("[CONNECTED]")


def subscribe_to_markets():
    global ws_instance
    
    print("Fetching active markets from API...")
    try:
        # Get active markets with trading activity
        resp = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={
                "closed": "false",
                "archived": "false",
                "limit": 10,
            }
        )
        markets = resp.json()
        
        print(f"Got {len(markets)} markets")
        
        token_ids = []
        for i, market in enumerate(markets[:5]):
            question = market.get("question", "?")[:50]
            
            # clobTokenIds is a JSON STRING that needs to be parsed!
            clob_tokens_raw = market.get("clobTokenIds", "[]")
            if isinstance(clob_tokens_raw, str):
                tokens = json.loads(clob_tokens_raw)
            else:
                tokens = clob_tokens_raw or []
            
            print(f"  Market {i+1}: {question}...")
            print(f"    Tokens: {len(tokens)}")
            if tokens:
                for t in tokens[:2]:
                    print(f"      - {t[:40]}...")
                token_ids.extend(tokens[:2])
        
        if not token_ids:
            print("No token IDs found!")
            return
            
        print(f"\nSubscribing to {len(token_ids)} tokens...")
        
        # Subscription message
        msg = {
            "type": "market",
            "assets_ids": token_ids,
        }
        ws_instance.send(json.dumps(msg))
        print(f"[SUBSCRIBED]")
        
    except Exception as e:
        print(f"Failed to fetch markets: {e}")
        import traceback
        traceback.print_exc()


def main():
    print("="*60)
    print("POLYMARKET WEBSOCKET RAW MESSAGE TEST")
    print("="*60)
    print(f"URL: {POLYMARKET_WS_URL}")
    print("Connecting...\n")
    
    ws = websocket.WebSocketApp(
        POLYMARKET_WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    
    def run_ws():
        ws.run_forever()
    
    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()
    
    # Wait for connection
    time.sleep(2)
    
    # Subscribe
    subscribe_to_markets()
    
    # Start ping loop
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
    
    try:
        print("\nCollecting messages for 30 seconds...")
        time.sleep(30)
    except KeyboardInterrupt:
        pass
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Message types received: {message_types}")
    print(f"Total unique messages stored: {len(received_messages)}")
    
    # Analyze price_change format
    price_changes = [m for m in received_messages if m.get("event_type") == "price_change"]
    if price_changes:
        print("\n--- PRICE_CHANGE ANALYSIS ---")
        pc = price_changes[0]
        print(f"Top-level keys: {list(pc.keys())}")
        changes = pc.get("price_changes", [])
        if changes:
            print(f"price_changes[0] keys: {list(changes[0].keys())}")
            print(f"Has 'asset_id' in price_changes[0]: {'asset_id' in changes[0]}")
            if 'asset_id' not in changes[0]:
                print(f"FULL CHANGE DATA: {json.dumps(changes[0], indent=2)}")
    else:
        print("\nNo price_change messages received!")
    
    ws.close()
    print("\nTest complete!")


if __name__ == "__main__":
    main()
