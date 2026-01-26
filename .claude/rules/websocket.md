# WebSocket Handling Patterns

## Non-JSON Messages
WebSocket servers can send non-JSON messages that need special handling:
- Heartbeats may send raw integers (e.g., `0`) instead of JSON
- Always check the data type after parsing before accessing properties

```python
data = json.loads(message)

# Handle non-dict messages (heartbeats send "0")
if not isinstance(data, dict):
    logger.debug("HEARTBEAT_RECEIVED", f"value={data}")
    return
```

## Ping/Pong Implementation
- Use a separate thread for sending pings to maintain connections
- Track last ping time for monitoring connection health
- Handle ping errors gracefully without crashing the main connection

```python
def _ping_loop(self):
    """Send periodic pings"""
    while self.running and self.connected:
        try:
            if self.ws:
                self.ws.send(json.dumps({"type": "ping"}))
                self.last_ping = time.time()
            time.sleep(self.config.ping_interval)
        except Exception as e:
            logger.error("PING_ERROR", str(e))
            break
```

## Connection Management
- Implement automatic reconnection with backoff
- Track reconnection attempts for monitoring
- Use daemon threads for WebSocket operations

## Mistakes to Avoid
- Do not assume all received messages will be valid JSON objects
- Do not rely solely on `json.JSONDecodeError` - errors can occur after successful parsing
- The `websocket-client` library may not catch all exceptions from callbacks
