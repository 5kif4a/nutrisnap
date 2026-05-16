"""Container healthcheck — ping the local /health endpoint."""

import sys
import urllib.error
import urllib.request


def main() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as r:
            return 0 if r.status == 200 else 1
    except (urllib.error.URLError, OSError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
