"""Bot container healthcheck — verifies the run_polling process is alive.

The bot has no HTTP port (it polls Telegram). Under watchfiles, PID 1 is
watchfiles itself and the bot is its child — so we scan /proc for any
process whose cmdline contains "run_polling".
"""

import os
import sys


def main() -> int:
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read()
        except OSError:
            continue
        if b"run_polling" in cmdline:
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
