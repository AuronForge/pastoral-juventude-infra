#!/usr/bin/env python3
"""Verify diagnostics, partial failures and host memory accounting."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('health', Path(__file__).with_name('health-development.py'))
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class DiagnosticsTest(unittest.TestCase):
    def test_host_memory_uses_available_including_reclaimable_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'meminfo'
            path.write_text('MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 200 kB\nSwapFree: 150 kB\n')
            result = health.memory(path)
            self.assertEqual(result['usedBytes'], 600 * 1024)
            self.assertEqual(result['usedPercent'], 60)
            self.assertEqual(result['swapUsedBytes'], 50 * 1024)

    def fixture(self, args):
        if args[1] == 'ps':
            return 'container-id\n'
        if args[1] == 'inspect':
            return json.dumps({'State': {'Status': 'running', 'Running': True,
                              'Health': {'Status': 'healthy'}, 'OOMKilled': False,
                              'StartedAt': '2026-10-01T00:00:00Z'},
                               'RestartCount': 0, 'HostConfig': {'Memory': 0}})
        if args[1] == 'stats':
            return json.dumps(dict.fromkeys(('CPUPerc', 'MemUsage', 'MemPerc', 'PIDs', 'BlockIO', 'NetIO'), '0'))
        if args[1] == 'exec':
            return json.dumps({'httpStatus': 200, 'body': {'status': 'ok',
                              'checks': {'database': 'up', 'cache': 'up'}}})
        raise AssertionError(args)

    def test_success_collects_all_containers_and_readiness(self):
        with patch.object(health, 'run', side_effect=self.fixture):
            result = health.collect(Path('/tmp'))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(set(result['containers']), set(health.SERVICES))
        self.assertEqual(result['readiness']['body']['checks']['database'], 'up')
        self.assertEqual(result['containers']['postgres']['configuredMemoryLimitBytes'], 0)

    def test_database_down_keeps_details_and_fails_status(self):
        def run(args):
            if args[1] == 'exec':
                return json.dumps({'httpStatus': 503, 'body': {'status': 'error',
                                  'checks': {'database': 'down', 'cache': 'up'}}})
            return self.fixture(args)
        with patch.object(health, 'run', side_effect=run):
            result = health.collect(Path('/tmp'))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['readiness']['body']['checks']['database'], 'down')

    def test_docker_unavailable_returns_partial_report(self):
        with patch.object(health, 'run', side_effect=FileNotFoundError):
            result = health.collect(Path('/tmp'))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(len(result['errors']), 5)
        self.assertIn('memory', result['host'])


if __name__ == '__main__':
    unittest.main()

