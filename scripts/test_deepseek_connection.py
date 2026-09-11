"""
Standalone sanity check: run this FIRST after setup to confirm your machine
can reach the DeepSeek API with the key in .env, before trying a real PDF.

    python scripts/test_deepseek_connection.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.deepseek_client import connectivity_self_test  # noqa: E402
from backend import config  # noqa: E402


def main():
    print(f"DeepSeek base URL : {config.DEEPSEEK_BASE_URL}")
    print(f"DeepSeek model    : {config.DEEPSEEK_MODEL}")
    print(f"API key present   : {'yes' if config.DEEPSEEK_API_KEY else 'NO — set DEEPSEEK_API_KEY in .env'}")
    print("Testing connection...")
    result = connectivity_self_test()
    if result["ok"]:
        print(f"\n✅ Connected. Model replied: {result['reply']!r}")
        print("You're good to go — run `python app.py` to start the app.")
    else:
        print(f"\n❌ Could not reach DeepSeek: {result['reason']}")
        print(
            "\nCommon causes:\n"
            "  - No internet access from this machine, or a firewall/proxy blocking api.deepseek.com\n"
            "  - The API key in .env is wrong or has been rotated\n"
            "  - DeepSeek's service is temporarily down\n"
            "\nThe app will still run without this working — it falls back to a raw,\n"
            "non-AI extraction (clearly labeled 'Raw extraction' in the UI) so you're never blocked."
        )
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
