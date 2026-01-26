# Error Handling Guidelines

## Specific Exception Handling
Catch specific exceptions rather than relying on generic exception handling:

```python
# Good - specific exceptions
try:
    data = json.loads(message)
except json.JSONDecodeError as e:
    logger.error("PARSE_ERROR", f"error={e}")

# Also handle AttributeError for unexpected data types
try:
    event_type = data.get("event_type")
except AttributeError:
    logger.warning("UNEXPECTED_TYPE", f"type={type(data)}")
```

## Type Validation
Implement type checks for received data before accessing attributes or methods:

```python
# Check type before accessing dict methods
if not isinstance(data, dict):
    logger.debug("NON_DICT_DATA", f"value={data}")
    return

# Safe attribute access
event_type = data.get("event_type")
```

## Error Logging
- Include relevant context in error logs
- Use key-value format for easy parsing
- Log the actual error message/exception

```python
logger.error("WS_ERROR", str(error))
logger.error("PARSE_ERROR", f"error={e} message={message[:100]}")
```

## Recovery Strategies
- Implement graceful degradation when errors occur
- Don't let one bad message crash the entire connection
- Log and continue for non-critical errors
