"""NaviPulse OpenAI diagnostic. Run from project root: python scripts/check_ai.py

Makes ONE small API request if a key is configured; can incur a small API charge.
Does not print keys, nor inspect or change SQLite records.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from disruption_iq import ai


if __name__ == '__main__':
    print('NaviPulse AI:', ai.availability())
    ok, detail = ai.probe()
    print('Connection:', 'SUCCESS' if ok else 'FAILED')
    print('Details:', detail)
    raise SystemExit(0 if ok else 1)
