"""
Unit tests for the Call Detail Records module
"""

import json
import os
import pathlib
import tempfile
import unittest
from datetime import datetime, timedelta

from ipswichsuite.cdr import CDRWriter


class TestCDRWriter(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmpdir.name) / 'cdr'

    def tearDown(self):
        self.tmpdir.cleanup()

    def _read_records(self):
        records = []
        for path in sorted(self.dir.glob('cdr-*.jsonl')):
            with open(path) as f:
                for line in f:
                    records.append(json.loads(line))
        return records

    def test_disabled_writes_nothing(self):
        writer = CDRWriter(directory=str(self.dir), enabled=False)
        writer.record_call(start_time=1000.0, end_time=1004.4, src_id=1,
                           dst_id=101, slot=1, call_type='group', repeater_id=312001)
        writer.close()
        self.assertFalse(self.dir.exists())

    def test_call_record(self):
        writer = CDRWriter(directory=str(self.dir), enabled=True)
        writer.record_call(
            start_time=1754140000.123, end_time=1754140004.523,
            src_id=31201010, dst_id=101, slot=1, call_type='group',
            repeater_id=312001, repeater_callsign='WQAB123',
            packets=264, end_reason='terminator', target_count=3,
            fleet='Acme Delivery', alias='Truck 10',
        )
        writer.close()

        records = self._read_records()
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r['type'], 'call')
        self.assertEqual(r['src_id'], 31201010)
        self.assertEqual(r['dst_id'], 101)
        self.assertEqual(r['slot'], 1)
        self.assertEqual(r['call_type'], 'group')
        self.assertEqual(r['duration'], 4.4)
        self.assertEqual(r['repeater_id'], 312001)
        self.assertEqual(r['repeater_callsign'], 'WQAB123')
        self.assertEqual(r['packets'], 264)
        self.assertEqual(r['targets'], 3)
        self.assertEqual(r['end_reason'], 'terminator')
        self.assertEqual(r['fleet'], 'Acme Delivery')
        self.assertEqual(r['alias'], 'Truck 10')
        self.assertIn('start_iso', r)

    def test_denial_record(self):
        writer = CDRWriter(directory=str(self.dir), enabled=True)
        writer.record_denial(
            src_id=31209999, dst_id=101, slot=1, repeater_id=312001,
            reason='unknown_subscriber', enforced=True,
        )
        writer.close()

        records = self._read_records()
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r['type'], 'deny')
        self.assertEqual(r['src_id'], 31209999)
        self.assertEqual(r['reason'], 'unknown_subscriber')
        self.assertTrue(r['enforced'])
        self.assertIsNone(r['fleet'])
        self.assertIsNone(r['alias'])

    def test_empty_metadata_becomes_null(self):
        writer = CDRWriter(directory=str(self.dir), enabled=True)
        writer.record_call(start_time=1000.0, end_time=1001.0, src_id=1,
                           dst_id=2, slot=1, call_type='group', repeater_id=3,
                           repeater_callsign='', fleet=None, alias='')
        writer.close()
        r = self._read_records()[0]
        self.assertIsNone(r['alias'])
        self.assertIsNone(r['fleet'])
        self.assertIsNone(r['repeater_callsign'])

    def test_daily_file_naming(self):
        writer = CDRWriter(directory=str(self.dir), enabled=True)
        writer.record_denial(src_id=1, dst_id=2, slot=1, repeater_id=3,
                             reason='x', enforced=False)
        writer.close()
        expected = f"cdr-{datetime.now().strftime('%Y%m%d')}.jsonl"
        self.assertTrue((self.dir / expected).exists())

    def test_append_across_reopen(self):
        writer = CDRWriter(directory=str(self.dir), enabled=True)
        writer.record_denial(src_id=1, dst_id=2, slot=1, repeater_id=3,
                             reason='x', enforced=False)
        writer.close()
        writer = CDRWriter(directory=str(self.dir), enabled=True)
        writer.record_denial(src_id=4, dst_id=5, slot=2, repeater_id=6,
                             reason='y', enforced=True)
        writer.close()
        self.assertEqual(len(self._read_records()), 2)

    def test_retention_cleanup(self):
        self.dir.mkdir(parents=True)
        old_date = (datetime.now() - timedelta(days=120)).strftime('%Y%m%d')
        recent_date = (datetime.now() - timedelta(days=5)).strftime('%Y%m%d')
        old_file = self.dir / f'cdr-{old_date}.jsonl'
        recent_file = self.dir / f'cdr-{recent_date}.jsonl'
        unrelated = self.dir / 'notes.txt'
        old_file.write_text('{}\n')
        recent_file.write_text('{}\n')
        unrelated.write_text('keep me\n')

        CDRWriter(directory=str(self.dir), retention_days=90, enabled=True)

        self.assertFalse(old_file.exists())
        self.assertTrue(recent_file.exists())
        self.assertTrue(unrelated.exists())

    def test_retention_zero_keeps_everything(self):
        self.dir.mkdir(parents=True)
        old_date = (datetime.now() - timedelta(days=3650)).strftime('%Y%m%d')
        old_file = self.dir / f'cdr-{old_date}.jsonl'
        old_file.write_text('{}\n')

        CDRWriter(directory=str(self.dir), retention_days=0, enabled=True)

        self.assertTrue(old_file.exists())

    def test_write_failure_never_raises(self):
        writer = CDRWriter(directory=str(self.dir), enabled=True)
        writer.close()
        # Simulate a dead handle by pointing the directory somewhere unwritable
        writer._dir = pathlib.Path('/nonexistent-root-path/cdr')
        writer._file = None
        # Must log, not raise
        writer.record_denial(src_id=1, dst_id=2, slot=1, repeater_id=3,
                             reason='x', enforced=True)


if __name__ == '__main__':
    unittest.main()
