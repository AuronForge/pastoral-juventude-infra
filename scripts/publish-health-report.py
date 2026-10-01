#!/usr/bin/env python3
"""Collect on Ubuntu and atomically publish to the selected daemon's volume."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess

spec = importlib.util.spec_from_file_location('health', Path(__file__).with_name('health-development.py'))
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


def publish(report, volume='pastoral-dev_health-report-data'):
    subprocess.run(['docker', 'volume', 'create', '--label',
                    'com.docker.compose.project=pastoral-dev', '--label',
                    'com.docker.compose.volume=health-report-data', volume],
                   check=True, stdout=subprocess.DEVNULL, timeout=30)
    report['collectedAt'] = datetime.now(timezone.utc).isoformat()
    subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none',
                    '--mount', f'type=volume,src={volume},dst=/data',
                    'alpine:3.22.1', 'sh', '-ec',
                    'umask 022; chmod 0755 /data; tmp=$(mktemp /data/health.XXXXXX); '
                    "trap 'rm -f \"$tmp\"' EXIT; cat > \"$tmp\"; chmod 0644 \"$tmp\"; mv \"$tmp\" /data/health.json"],
                   input=json.dumps(report), text=True, check=True, timeout=90)


if __name__ == '__main__':
    endpoint_file = Path('/opt/pastoral/dev/docker-host')
    endpoint = os.environ.get('DOCKER_HOST') or (
        endpoint_file.read_text().strip() if endpoint_file.exists() else 'unix:///var/run/docker.sock')
    if not endpoint.startswith('unix:///') or any(char.isspace() for char in endpoint):
        raise SystemExit('Invalid development Docker endpoint')
    os.environ['DOCKER_HOST'] = endpoint
    os.environ.pop('DOCKER_CONTEXT', None)
    result = health.collect()
    publish(result)
    print(f"Published health report: {result['status']}")
