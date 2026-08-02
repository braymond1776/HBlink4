"""
Call Detail Records (CDR) for HBlink4

Commercial (Part 90) system operators need an auditable, machine-readable
record of every call for billing, capacity planning, and incident review.
This module appends one JSON object per line (JSONL) to a daily CDR file:

    logs/cdr/cdr-YYYYMMDD.jsonl

Record types:
    call    - A completed transmission (written when the stream ends)
    deny    - A rejected or flagged access attempt (subscriber ACL)

JSONL was chosen over a database so records can be consumed with standard
tools (jq, awk, spreadsheet import) and shipped to any billing pipeline.
Volume is bounded by human speech - one record per PTT release - so a
plain append with flush is more than fast enough and survives crashes.

Copyright (C) 2025 HBlink4 Part 90 contributors
License: GNU GPLv3 (as part of the HBlink4 combined work)
"""

import json
import logging
import pathlib
from datetime import datetime, timedelta
from time import time
from typing import Any, Dict, Optional, TextIO

LOGGER = logging.getLogger(__name__)


class CDRWriter:
    """
    Append-only daily-rotating JSONL writer for call detail records.

    All writes are line-buffered appends with an explicit flush so records
    survive an unclean shutdown. File handles roll over at local midnight;
    files older than retention_days are removed at startup and rollover.
    """

    def __init__(self, directory: str = 'logs/cdr', retention_days: int = 90,
                 enabled: bool = True):
        self.enabled = enabled
        self.retention_days = retention_days
        self._dir = pathlib.Path(directory)
        self._file: Optional[TextIO] = None
        self._file_date: Optional[str] = None

        if not self.enabled:
            return

        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._cleanup_old_files()
            LOGGER.info(f'CDR writer initialized: directory={self._dir}, '
                        f'retention={retention_days} days')
        except OSError as e:
            LOGGER.error(f'CDR writer disabled - cannot prepare {self._dir}: {e}')
            self.enabled = False

    # --------------------------------------------------------------- records

    def record_call(self, *, start_time: float, end_time: float,
                    src_id: int, dst_id: int, slot: int, call_type: str,
                    repeater_id: int, repeater_callsign: str = '',
                    packets: int = 0, end_reason: str = '',
                    target_count: int = 0, fleet: Optional[str] = None,
                    alias: str = '') -> None:
        """Write a record for one completed transmission"""
        self._write({
            'type': 'call',
            'start': round(start_time, 3),
            'end': round(end_time, 3),
            'start_iso': self._iso(start_time),
            'duration': round(end_time - start_time, 2),
            'src_id': src_id,
            'alias': alias or None,
            'fleet': fleet,
            'dst_id': dst_id,
            'slot': slot,
            'call_type': call_type,
            'repeater_id': repeater_id,
            'repeater_callsign': repeater_callsign or None,
            'packets': packets,
            'targets': target_count,
            'end_reason': end_reason,
        })

    def record_denial(self, *, src_id: int, dst_id: int, slot: int,
                      repeater_id: int, reason: str, enforced: bool,
                      fleet: Optional[str] = None, alias: str = '') -> None:
        """
        Write a record for a rejected (or, in permissive mode, flagged)
        access attempt. enforced=False marks permissive-mode records where
        the traffic was still passed.
        """
        self._write({
            'type': 'deny',
            'time': round(time(), 3),
            'time_iso': self._iso(time()),
            'src_id': src_id,
            'alias': alias or None,
            'fleet': fleet,
            'dst_id': dst_id,
            'slot': slot,
            'repeater_id': repeater_id,
            'reason': reason,
            'enforced': enforced,
        })

    # -------------------------------------------------------------- plumbing

    @staticmethod
    def _iso(epoch: float) -> str:
        return datetime.fromtimestamp(epoch).isoformat(timespec='seconds')

    def _write(self, record: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            f = self._get_file()
            f.write(json.dumps(record, separators=(',', ':')) + '\n')
            f.flush()
        except Exception as e:
            # CDR failures must never disturb call handling
            LOGGER.error(f'CDR write failed: {e}')

    def _get_file(self) -> TextIO:
        """Return today's file handle, rolling over at date change"""
        today = datetime.now().strftime('%Y%m%d')
        if self._file is None or self._file_date != today:
            if self._file:
                try:
                    self._file.close()
                except OSError:
                    pass
                self._cleanup_old_files()
            path = self._dir / f'cdr-{today}.jsonl'
            self._file = open(path, 'a', encoding='utf-8')
            self._file_date = today
        return self._file

    def _cleanup_old_files(self) -> None:
        """Remove CDR files older than the retention window"""
        if self.retention_days <= 0:
            return  # Retention disabled - keep everything
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        for path in self._dir.glob('cdr-*.jsonl'):
            try:
                date_str = path.stem.split('-', 1)[1]
                file_date = datetime.strptime(date_str, '%Y%m%d')
                if file_date < cutoff:
                    path.unlink()
                    LOGGER.info(f'Removed CDR file past retention: {path.name}')
            except (ValueError, IndexError):
                continue  # Not one of our files
            except OSError as e:
                LOGGER.warning(f'Could not remove old CDR file {path.name}: {e}')

    def close(self) -> None:
        """Flush and close the current file"""
        if self._file:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
            self._file_date = None
