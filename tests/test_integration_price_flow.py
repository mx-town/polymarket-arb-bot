#!/usr/bin/env python3
"""
Integration test to verify the full data flow:
1. Load markets from API
2. Set up state manager with token mappings
3. Connect to WebSocket
4. Process price_change events
5. Verify state updates
"""

import json
import time
import threading
import requests
import websocket

import sys
sys.path.insert(0, "/Users/thedoc/conductor/workspaces/polymarket-arb-bot/milan")

from src.market.state import MarketState, MarketStateManager, MarketStatus

POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

def parse_json_field(value) -> list:
    """Parse a JSON string field or return as-is if already parsed"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def load_markets(limit=5):
    """Load markets from Polymarket API"""
    print(f"Loading {limit} markets from API...")
    
    resp = requests.get(
        "https://gamma-api.polymarket.com/markets",
        params={
            "closed": "false",
            "archived": "false",
            "limit": limit,
        }
    )
    markets = resp.json()
    print(f"Got {len(markets)} markets")
    return markets


def setup_state_manager(markets) -> MarketStateManager:
    """Set up state manager from market data"""
    state_manager = MarketStateManager()
    
    for market in markets:
        # Parse clobTokenIds (it's a JSON string!)
        clob_tokens = parse_json_field(market.get("clobTokenIds"))
        outcomes = parse_json_field(market.get("outcomes"))
        
        if len(clob_tokens) < 2 or len(outcomes) < 2:
            continue
        
        # For simplicity, treat first token as "up" and second as "down"
        state = MarketState(
            market_id=market.get("conditionId", ""),
            slug=market.get("slug", ""),
            question=market.get("question", "")[:50],
            up_token_id=clob_tokens[0],
            down_token_id=clob_tokens[1],
        )
        
        state_manager.add_market(state)
        print(f"  Added market: {state.slug[:40]}...")
        print(f"    Up token:   {state.up_token_id[:30]}...")
        print(f"    Down token: {state.down_token_id[:30]}...")
    
    return state_manager


def test_price_change_handling(state_manager, price_change_data):
    """Test the _handle_price_change logic"""
    print("\n--- Testing price_change handling ---")
    print(f"Event keys: {list(price_change_data.keys())}")
    
    changes = price_change_data.get("price_changes", [])
    if not changes or not isinstance(changes, list):
        print("ERROR: No price_changes array")
        return False
    
    print(f"Num changes: {len(changes)}")
    
    for i, change in enumerate(changes):
        if not isinstance(change, dict):
            print(f"  Change {i}: not a dict, skipping")
            continue
        
        asset_id = change.get("asset_id")
        if not asset_id:
            print(f"  Change {i}: no asset_id, keys={list(change.keys())}")
            continue
        
        print(f"\n  Change {i}:")
        print(f"    asset_id: {asset_id[:30]}...")
        
        # Check if this token is registered
        market = state_manager.get_market_by_token(asset_id)
        if market:
            print(f"    FOUND in state manager!")
            print(f"    Market: {market.slug[:40]}...")
            is_up = state_manager.is_up_token(asset_id)
            print(f"    Is UP token: {is_up}")
            
            best_bid = float(change.get("best_bid", 0))
            best_ask = float(change.get("best_ask", 0))
            print(f"    best_bid: {best_bid}, best_ask: {best_ask}")
            
            if best_bid > 0 and best_ask > 0:
                state_manager.update_from_book(asset_id, best_bid, best_ask)
                print(f"    State updated!")
                
                # Verify
                if is_up:
                    print(f"    Verified - up_best_bid: {market.up_best_bid}, up_best_ask: {market.up_best_ask}")
                else:
                    print(f"    Verified - down_best_bid: {market.down_best_bid}, down_best_ask: {market.down_best_ask}")
                return True
        else:
            print(f"    NOT FOUND in state manager")
            print(f"    Registered tokens:")
            for tid in list(state_manager._token_to_market.keys())[:5]:
                print(f"      - {tid[:30]}...")
    
    return False


def main():
    print("="*60)
    print("INTEGRATION TEST: Price Change Flow")
    print("="*60)
    
    # Step 1: Load markets
    markets = load_markets(limit=5)
    
    # Step 2: Set up state manager
    print("\n--- Setting up state manager ---")
    state_manager = setup_state_manager(markets)
    print(f"State manager has {len(state_manager.markets)} markets")
    print(f"Token mappings: {len(state_manager._token_to_market)} tokens")
    
    # Step 3: Get token IDs for subscription
    token_ids = state_manager.get_all_token_ids()
    print(f"\nToken IDs for subscription: {len(token_ids)}")
    
    # Step 4: Connect to WebSocket and capture a price_change
    print("\n--- Connecting to WebSocket ---")
    
    received_price_change = None
    
    def on_message(ws, message):
        nonlocal received_price_change
        
        if isinstance(message, bytes) or not message.startswith('{'):
            return
        
        try:
            data = json.loads(message)
            if isinstance(data, dict) and data.get("event_type") == "price_change":
                received_price_change = data
                print("Received price_change event!")
                ws.close()
        except:
            pass
    
    def on_open(ws):
        print("[CONNECTED]")
        msg = {"type": "market", "assets_ids": token_ids}
        ws.send(json.dumps(msg))
        print(f"[SUBSCRIBED] to {len(token_ids)} tokens")
    
    def on_error(ws, error):
        print(f"[ERROR] {error}")
    
    ws = websocket.WebSocketApp(
        POLYMARKET_WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
    )
    
    def ping_loop():
        while True:
            try:
                time.sleep(5)
                ws.send("ping")
            except:
                break
    
    # Run WebSocket in thread
    ws_thread = threading.Thread(target=lambda: ws.run_forever(), daemon=True)
    ws_thread.start()
    
    ping_thread = threading.Thread(target=ping_loop, daemon=True)
    
    # Wait for price_change
    print("Waiting for price_change event (max 60 seconds)...")
    time.sleep(2)
    ping_thread.start()
    
    for _ in range(60):
        if received_price_change:
            break
        time.sleep(1)
    
    if not received_price_change:
        print("FAILED: No price_change received in 60 seconds")
        return
    
    # Step 5: Test price_change handling
    success = test_price_change_handling(state_manager, received_price_change)
    
    print("\n" + "="*60)
    if success:
        print("SUCCESS: Price change was processed and state was updated!")
    else:
        print("FAILED: Price change was NOT processed correctly")
    print("="*60)


if __name__ == "__main__":
    main()
