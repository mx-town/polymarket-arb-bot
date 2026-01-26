# Polymarket Arbitrage Bot - Development Guidelines

## Project Overview
Python arbitrage bot connecting to Polymarket CLOB and Binance via WebSocket for real-time price data and trading.

## Coding Conventions

### Logging
- Use descriptive log messages with key-value pairs for easier parsing
- Format: `logger.info("ACTION_NAME", "key=value key2=value2")`
- Examples:
  ```python
  logger.info("CONNECTING", POLYMARKET_WS_URL)
  logger.info("SUBSCRIBED", f"tokens={len(token_ids)}")
  logger.warning("RECONNECTING", f"attempt={self.reconnect_count}")
  ```

### Communication Preferences
- Provide clear explanations of identified issues and proposed solutions
- Confirm fixes via logs or code snippets
- Prompt for confirmation before making changes ("Should I fix this?")
- Confirm when PRs have been successfully created

## Best Practices

### Root Cause Analysis
- Thoroughly investigate error logs and code to pinpoint exact causes
- Apply minimal necessary code changes to resolve specific bugs
- Verify fixes by re-checking logs or code
- Communicate: explain the problem, the solution, and how to verify

### PR Workflow
- Create focused PRs with clear descriptions
- Include test verification in PR descriptions
- Confirm PR creation with the user
