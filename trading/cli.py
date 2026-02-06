"""
Trading Bot CLI - arb-bot command.

Commands:
  arb-bot trade [OPTIONS]    Run trading bot
  arb-bot status             Check if running
  arb-bot stop [--force]     Stop the bot
"""

import argparse
import os
import signal
import sys
from pathlib import Path


def cmd_trade(args: argparse.Namespace) -> int:
    """Run the trading bot (always uses lag_arb strategy)."""
    # Import here to avoid circular imports
    from trading.bot import main as bot_main

    if args.api_mode:
        # Emit stage markers for API subprocess parsing
        print("BOT_START", flush=True)

    # Rewrite sys.argv so build_config()/parse_args() in bot.py sees
    # only the flags it understands (it has its own argparse parser).
    argv = [sys.argv[0], "--config", str(args.config)]
    if args.live:
        argv.append("--live")
    if args.verbose:
        argv.append("--verbose")
    sys.argv = argv

    # Run the bot (uses default config loading from build_config)
    return bot_main()


def cmd_status(args: argparse.Namespace) -> int:
    """Check if bot is running."""
    pid_file = Path("/tmp/polymarket_bot.pid")

    if not pid_file.exists():
        print("Bot is not running (no PID file)")
        return 1

    try:
        pid = int(pid_file.read_text().strip())
        # Check if process exists
        os.kill(pid, 0)
        print(f"Bot is running (PID: {pid})")
        return 0
    except (ValueError, ProcessLookupError):
        print("Bot is not running (stale PID file)")
        return 1
    except PermissionError:
        print(f"Bot is running (PID: {pid}) - permission denied to check")
        return 0


def cmd_stop(args: argparse.Namespace) -> int:
    """Stop the bot."""
    pid_file = Path("/tmp/polymarket_bot.pid")

    if not pid_file.exists():
        print("Bot is not running (no PID file)")
        return 1

    try:
        pid = int(pid_file.read_text().strip())
        sig = signal.SIGKILL if args.force else signal.SIGTERM
        os.kill(pid, sig)
        print(f"Sent {'SIGKILL' if args.force else 'SIGTERM'} to bot (PID: {pid})")
        return 0
    except (ValueError, ProcessLookupError):
        print("Bot is not running")
        return 1
    except PermissionError:
        print(f"Permission denied to stop bot (PID: {pid})")
        return 1


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="arb-bot",
        description="Polymarket Arbitrage Trading Bot",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # trade command
    trade_parser = subparsers.add_parser("trade", help="Run the trading bot (lag_arb strategy)")
    trade_parser.add_argument(
        "--config",
        type=str,
        default="config/default.yaml",
        help="Path to config file",
    )
    trade_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run in dry-run mode (no trades)",
    )
    trade_parser.add_argument(
        "--live",
        action="store_true",
        help="Run in live mode (execute trades)",
    )
    trade_parser.add_argument(
        "--api-mode",
        action="store_true",
        help="Emit JSON stage markers on stdout (for API subprocess)",
    )
    trade_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # status command
    status_parser = subparsers.add_parser("status", help="Check if bot is running")

    # stop command
    stop_parser = subparsers.add_parser("stop", help="Stop the bot")
    stop_parser.add_argument(
        "--force",
        action="store_true",
        help="Force kill (SIGKILL instead of SIGTERM)",
    )

    args = parser.parse_args()

    if args.command is None:
        # Default to trade if no command specified
        args.command = "trade"
        args.config = "config/default.yaml"
        args.dry_run = True
        args.live = False
        args.api_mode = False
        args.verbose = False

    # Handle --live overriding --dry-run
    if hasattr(args, "live") and args.live:
        args.dry_run = False

    if args.command == "trade":
        return cmd_trade(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "stop":
        return cmd_stop(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
