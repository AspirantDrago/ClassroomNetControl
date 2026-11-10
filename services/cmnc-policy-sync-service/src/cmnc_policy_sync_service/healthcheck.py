import sys
import urllib.request
from cmnc_policy_sync_service.settings import settings

def main():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{settings.port}/health", timeout=3) as response:
            if response.status != 200:
                raise RuntimeError("Policy sync health probe rejected")
    except Exception as exc:
        print(f"unhealthy: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("healthy")

if __name__ == "__main__":
    main()
