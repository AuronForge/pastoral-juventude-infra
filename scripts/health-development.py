#!/usr/bin/env python3
"""Read-only diagnostics on the Ubuntu Docker host; never an HTTP endpoint."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

SERVICES = ('backend', 'postgres', 'redis', 'traefik', 'frontend')


def run(args):
    return subprocess.check_output(args, text=True, timeout=15, stderr=subprocess.DEVNULL)


def memory(path=Path('/proc/meminfo')):
    values = {}
    for line in path.read_text().splitlines():
        key, value = line.split(':', 1)
        values[key] = int(value.split()[0]) * 1024
    total, available = values['MemTotal'], values['MemAvailable']
    return {'totalBytes': total, 'availableBytes': available,
            'usedBytes': total - available,
            'usedPercent': round((total - available) / total * 100, 2),
            'swapTotalBytes': values['SwapTotal'],
            'swapUsedBytes': values['SwapTotal'] - values['SwapFree']}


def collect(root=Path('/opt/pastoral/dev')):
    report = {'timestamp': datetime.now(timezone.utc).isoformat(),
              'dockerHost': os.environ.get('DOCKER_HOST', 'unix:///var/run/docker.sock'),
              'host': {}, 'containers': {}, 'readiness': None, 'errors': []}
    try:
        disk = shutil.disk_usage(root)
        report['host'] = {'memory': memory(), 'loadAverage': list(os.getloadavg()),
                          'cpuCount': os.cpu_count(),
                          'disk': {'path': str(root), 'totalBytes': disk.total,
                                   'freeBytes': disk.free, 'usedBytes': disk.used},
                          'uptimeSeconds': float(Path('/proc/uptime').read_text().split()[0])}
    except (OSError, ValueError, KeyError):
        report['errors'].append('host_metrics_unavailable')
    for service in SERVICES:
        try:
            ids = run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=pastoral-dev',
                       '--filter', f'label=com.docker.compose.service={service}',
                       '--filter', 'label=com.docker.compose.oneoff=False']).split()
            if len(ids) != 1:
                raise ValueError('Missing or ambiguous service')
            container = json.loads(run(['docker', 'inspect', '--format',
                                        '{{json .}}', ids[0]]))
            state = container['State']
            item = {'status': state['Status'],
                    'health': state.get('Health', {}).get('Status', 'not_configured'),
                    'restartCount': container['RestartCount'],
                    'oomKilled': state['OOMKilled'],
                    'startedAt': state['StartedAt'],
                    'configuredMemoryLimitBytes': container['HostConfig']['Memory'],
                    'stats': None}
            report['containers'][service] = item
            if state['Running']:
                stats = json.loads(run(['docker', 'stats', '--no-stream',
                                        '--format', '{{json .}}', ids[0]]))
                item['stats'] = {key: stats[key] for key in
                                 ('CPUPerc', 'MemUsage', 'MemPerc', 'PIDs', 'BlockIO', 'NetIO')}
            if service == 'backend' and state['Running']:
                probe = "const r=await fetch('http://127.0.0.1:3000/health/ready',{signal:AbortSignal.timeout(4000)}); console.log(JSON.stringify({httpStatus:r.status,body:await r.json()}));"
                report['readiness'] = json.loads(run(['docker', 'exec', ids[0], 'node',
                                                     '--input-type=module', '-e', probe]))
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            report['errors'].append(f'{service}_diagnostics_unavailable')
    healthy = (report['readiness'] is not None and report['readiness']['httpStatus'] == 200
               and not report['errors'] and all(
                   item['status'] == 'running' and item['health'] != 'unhealthy'
                   for item in report['containers'].values()))
    report['status'] = 'ok' if healthy else 'error'
    return report


if __name__ == '__main__':
    endpoint_file = Path('/opt/pastoral/dev/docker-host')
    endpoint = os.environ.get('DOCKER_HOST') or (
        endpoint_file.read_text().strip() if endpoint_file.exists() else 'unix:///var/run/docker.sock')
    if not endpoint.startswith('unix:///') or any(char.isspace() for char in endpoint):
        raise SystemExit('Invalid development Docker endpoint')
    os.environ['DOCKER_HOST'] = endpoint
    os.environ.pop('DOCKER_CONTEXT', None)
    result = collect()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['status'] == 'ok' else 1)
