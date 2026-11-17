#!/usr/bin/env python3
"""Wait for post-boot activity before starting trials; no settings changed."""
import json
import os
from pathlib import Path
import time

begin = time.monotonic()
stable = 0
while time.monotonic() - begin < 900:
    uptime = float(Path('/proc/uptime').read_text().split()[0])
    load = os.getloadavg()[0]
    stable = stable + 1 if uptime >= 240 and load < 0.6 else 0
    print(json.dumps({'uptime_seconds': uptime, 'load_1m': load, 'stable_checks': stable}), flush=True)
    if stable >= 3:
        break
    time.sleep(10)
else:
    raise SystemExit('VM did not settle within 15 minutes')
