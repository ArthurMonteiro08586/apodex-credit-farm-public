# -*- coding: utf-8 -*-
"""
bridge_keeper.py — keeps the Apodex bridge pool fresh 24/7.

Consumer access_tokens live ~1h. This keeper loops forever:
  1. sleep KEEP_MINUTES (default 40)
  2. run bridge_reauth.py to revive tokens via passwordless OTP
     (GMAIL_USER / GMAIL_APP_PASS must be in env)
  3. the bridge hot-reloads accounts_web.json automatically (mtime check)

Usage:
  export GMAIL_USER=you@gmail.com GMAIL_APP_PASS=xxxx
  python bridge_keeper.py            # revive every 40 min
  KEEP_MINUTES=25 python bridge_keeper.py

The bridge itself:
  python apodex_bridge.py            # http://127.0.0.1:8420/v1
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KEEP_MINUTES = int(os.environ.get('KEEP_MINUTES', '40'))
PYTHON = sys.executable


def revive_once():
    """Run bridge_reauth.py once; returns (revived, failed) from its log."""
    t0 = time.time()
    print(f'[keeper] {time.strftime("%H:%M:%S")} reauth start', flush=True)
    p = subprocess.run(
        [PYTHON, os.path.join(HERE, 'bridge_reauth.py')],
        capture_output=True, text=True, timeout=5400, cwd=HERE)
    out = (p.stdout or '') + (p.stderr or '')
    revived = out.count('REVIVED')
    dead = out.count('dead, skip') + out.count('no OTP') + out.count('never ok')
    print(f'[keeper] reauth done rc={p.returncode} revived={revived} dead={dead} '
          f'in {time.time()-t0:.0f}s', flush=True)
    return revived, dead


def main():
    if not os.environ.get('GMAIL_USER') or not os.environ.get('GMAIL_APP_PASS'):
        print('[keeper] GMAIL_USER / GMAIL_APP_PASS not set — OTP reads will fail', flush=True)
    while True:
        try:
            revive_once()
        except Exception as e:
            print('[keeper] reauth crashed:', e, flush=True)
        print(f'[keeper] sleeping {KEEP_MINUTES} min', flush=True)
        time.sleep(KEEP_MINUTES * 60)


if __name__ == '__main__':
    main()
