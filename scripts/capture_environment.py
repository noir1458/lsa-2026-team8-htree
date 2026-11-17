#!/usr/bin/env python3
import datetime
import json
import os
from pathlib import Path
import platform
import subprocess

cpu = {}
for line in Path('/proc/cpuinfo').read_text().splitlines():
    if not line.strip():
        break
    if ':' in line:
        key, value = map(str.strip, line.split(':', 1))
        if key in ('vendor_id', 'model name', 'cpu MHz', 'cache size', 'cpu cores', 'siblings', 'flags'):
            cpu[key] = value
data = {
    'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'kernel': platform.release(), 'machine': platform.machine(),
    'cpu_count': os.cpu_count(), 'cpu': cpu,
    'memory': Path('/proc/meminfo').read_text(),
    'uptime': Path('/proc/uptime').read_text().strip(),
    'loadavg': list(os.getloadavg()),
    'gcc': subprocess.check_output(['gcc', '--version'], text=True).splitlines()[0],
    'os_release': Path('/etc/os-release').read_text(),
    'virtualization': subprocess.run(['systemd-detect-virt'], text=True, stdout=subprocess.PIPE).stdout.strip(),
    'note': 'Hostname and login identity intentionally omitted.'
}
print(json.dumps(data, ensure_ascii=False, indent=2))
