"""Run the existing receipt tool and private booking API on one paid instance."""
import os
import signal
import subprocess
import sys
import time

children = []
def stop(*_):
    for child in children:
        if child.poll() is None: child.terminate()
    for child in children:
        try: child.wait(timeout=10)
        except subprocess.TimeoutExpired: child.kill()
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
children.append(subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', 'receipt_app.py',
    '--server.port=8501', '--server.address=127.0.0.1', '--server.headless=true']))
children.append(subprocess.Popen([sys.executable, '-m', 'gunicorn', '--bind', '127.0.0.1:8502',
    '--workers', '1', '--threads', '4', '--timeout', '90', 'booking_service.wsgi:app']))
children.append(subprocess.Popen(['.bin/caddy', 'run', '--config', 'Caddyfile']))
while True:
    for child in children:
        if child.poll() is not None:
            code = child.returncode
            for other in children:
                if other.poll() is None: other.terminate()
            sys.exit(code or 1)
    time.sleep(1)
