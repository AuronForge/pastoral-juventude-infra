#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import json
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('publisher', Path(__file__).with_name('publish-health-report.py'))
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class PublisherTest(unittest.TestCase):
    def test_partial_report_is_published_as_json_with_completion_time(self):
        report = {'status': 'error', 'errors': ['host_metrics_unavailable']}
        with patch.object(publisher.subprocess, 'run') as run:
            publisher.publish(report, 'test-volume')
        command = run.call_args
        self.assertEqual(json.loads(command.kwargs['input'])['status'], 'error')
        self.assertIn('collectedAt', json.loads(command.kwargs['input']))
        self.assertIn('type=volume,src=test-volume,dst=/data', command.args[0])

    def test_failed_volume_creation_prevents_publication(self):
        with patch.object(publisher.subprocess, 'run', side_effect=OSError), self.assertRaises(OSError):
            publisher.publish({'status': 'ok'})


if __name__ == '__main__':
    unittest.main()
