#!/usr/bin/env python3
"""Real image and atomic volume publishing, including non-root read access."""
from datetime import datetime, timezone, timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import uuid
import time

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('publisher', ROOT / 'scripts/publish-health-report.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
name = 'health-report-test-' + uuid.uuid4().hex
image = name + ':test'
container = None


def probe(path='/health/ready'):
    code = f"const r=await fetch('http://127.0.0.1:8080{path}'); console.log(JSON.stringify({{status:r.status,body:await r.json()}}));"
    return json.loads(subprocess.check_output(['docker', 'exec', container, 'node',
        '--input-type=module', '-e', code], text=True))


try:
    subprocess.run(['docker', 'build', '-t', image, '-f', str(ROOT / 'docker/health-report/Dockerfile'), str(ROOT)], check=True)
    subprocess.run(['docker', 'volume', 'create', name], check=True)
    container = subprocess.check_output(['docker', 'run', '-d', '--network', 'none', '--read-only',
        '--mount', f'type=volume,src={name},dst=/data,readonly',
        '-e', 'BACKEND_HEALTH_URL=http://127.0.0.1:8080/health/live', image], text=True).strip()
    deadline = time.monotonic() + 30
    while True:
        try:
            if probe('/health/live')['status'] == 200:
                break
        except subprocess.CalledProcessError:
            pass
        if time.monotonic() >= deadline:
            raise AssertionError('Health report did not start')
        time.sleep(0.25)
    assert probe()['status'] == 503
    report = {'timestamp': datetime.now(timezone.utc).isoformat(), 'host': {'cpuCount': 4},
        'containers': {}, 'errors': [], 'status': 'ok', 'readiness': None}
    publisher.publish(report, name)
    result = probe()
    assert result['status'] == 200, result
    assert result['body']['host']['cpuCount'] == 4
    report['status'] = 'error'
    report['errors'] = ['postgres_diagnostics_unavailable']
    publisher.publish(report, name)
    assert probe()['status'] == 503
    # Publish an expired sample through the same helper, without publisher resetting its date.
    report['status'] = 'ok'; report['errors'] = []
    report['collectedAt'] = (datetime.now(timezone.utc) - timedelta(seconds=181)).isoformat()
    subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none', '--mount',
        f'type=volume,src={name},dst=/data', 'alpine:3.22.1', 'sh', '-ec',
        'cat > /data/health.json; chmod 0644 /data/health.json'], input=json.dumps(report), text=True, check=True)
    assert probe()['body']['snapshot']['stale'] is True
    print('Health image: non-root volume reads, atomic publishing, absence, partial failure and stale report passed')
finally:
    if container:
        subprocess.run(['docker', 'rm', '-f', container], check=False)
    subprocess.run(['docker', 'volume', 'rm', name], check=False)
    subprocess.run(['docker', 'image', 'rm', image], check=False)
