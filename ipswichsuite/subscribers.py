"""
Part 90 subscriber (radio ID) access control for IpswichSuite

Commercial (FCC Part 90) DMR networks are closed systems: only radios that
have been provisioned by the system operator may transmit. This module
provides the subscriber database ("fleet map") and the per-call
authorization check that enforces it.

Concepts:
    Fleet       - A customer or agency. Owns blocks of radio IDs and a set
                  of talkgroups its radios may use.
    Subscriber  - An individual radio, identified by DMR radio ID. May be
                  listed explicitly (to attach an alias, disable a stolen or
                  retired radio, or override talkgroup permissions) or
                  implicitly authorized by a fleet ID range.

Enforcement modes (set in the subscriber file's "enforcement" section):
    disabled    - No checks. Behaves exactly like pre-Part 90 IpswichSuite.
    permissive  - Checks run and violations are logged/recorded, but all
                  traffic is still passed. Use while building the fleet map
                  on a live system.
    enforce     - Violations are denied. Production mode for closed systems.

The subscriber file is hot-reloadable: edits are picked up automatically
(mtime-based) without restarting the server, so radios can be added or a
stolen radio disabled with zero downtime. A file that fails to parse never
replaces the last known-good database.

Copyright (C) 2025-2026 Ipswich River Labs, LLC
License: GNU GPLv3 (as part of the IpswichSuite combined work)
"""

import json
import logging
import os
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

LOGGER = logging.getLogger(__name__)

VALID_MODES = ('disabled', 'permissive', 'enforce')

# Decision reason codes
REASON_DISABLED = 'acl_disabled'            # ACL not active, no check performed
REASON_AUTHORIZED = 'authorized'            # Subscriber authorized for this call
REASON_UNKNOWN = 'unknown_subscriber'       # Radio ID not in any fleet
REASON_SUBSCRIBER_DISABLED = 'subscriber_disabled'  # Radio explicitly disabled
REASON_FLEET_DISABLED = 'fleet_disabled'    # Entire fleet disabled
REASON_TG_DENIED = 'talkgroup_denied'       # Radio not authorized for this TG


class SubscriberConfigError(Exception):
    """Raised when the subscriber database file is structurally invalid"""


@dataclass
class SubscriberEntry:
    """An explicitly-listed radio"""
    radio_id: int
    alias: str = ''
    enabled: bool = True
    # None = inherit from fleet, [] = deny all, [ints] = only these TGs
    talkgroups: Optional[set] = None


@dataclass
class Fleet:
    """A customer/agency owning radio IDs and talkgroups"""
    name: str
    description: str = ''
    enabled: bool = True
    ids: set = field(default_factory=set)
    id_ranges: List[Tuple[int, int]] = field(default_factory=list)
    # None = allow all TGs, [] = deny all, [ints] = only these TGs
    talkgroups: Optional[set] = None
    # Optional per-slot overrides of the fleet talkgroup list
    slot1_talkgroups: Optional[set] = None
    slot2_talkgroups: Optional[set] = None
    subscribers: Dict[int, SubscriberEntry] = field(default_factory=dict)


@dataclass
class AccessDecision:
    """Result of a subscriber authorization check"""
    allowed: bool               # Final verdict (True in permissive mode even on violation)
    reason: str                 # One of the REASON_* codes
    would_deny: bool = False    # True in permissive mode when enforce would have denied
    fleet: Optional[str] = None
    alias: str = ''


def _parse_tg_list(value: Any, context: str) -> Optional[set]:
    """Parse a talkgroup list: None/absent = allow all, [] = deny all"""
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(t, int) and t >= 0 for t in value):
        raise SubscriberConfigError(f'{context}: talkgroups must be a list of non-negative integers')
    return set(value)


def _parse_radio_id(value: Any, context: str) -> int:
    if not isinstance(value, int) or not (0 < value <= 0xFFFFFF):
        raise SubscriberConfigError(f'{context}: radio ID must be an integer between 1 and 16777215')
    return value


class SubscriberACL:
    """
    Subscriber database with fast per-call authorization checks.

    Lookup cost per stream start: one dict hit for explicitly-listed radios,
    or one binary search over fleet ID ranges. Checks run once per stream
    (at stream start), never per packet.
    """

    def __init__(self, config: Dict[str, Any], source_path: Optional[str] = None):
        self._source_path = source_path
        self._file_sig: Optional[Tuple[float, int]] = None
        self.mode = 'disabled'
        self.reload_interval = 60
        self.fleets: List[Fleet] = []
        # Exact-ID index: radio_id -> (fleet, entry or None)
        self._exact: Dict[int, Tuple[Fleet, Optional[SubscriberEntry]]] = {}
        # Range index sorted by start for bisect: parallel lists
        self._range_starts: List[int] = []
        self._ranges: List[Tuple[int, int, Fleet]] = []

        self._load(config)
        if source_path:
            self._file_sig = self._stat_file(source_path)

    # ------------------------------------------------------------------ load

    @classmethod
    def from_file(cls, path: str) -> 'SubscriberACL':
        """Load the subscriber database from a JSON file (raises on error)"""
        with open(path, 'r') as f:
            config = json.load(f)
        return cls(config, source_path=path)

    @staticmethod
    def _stat_file(path: str) -> Optional[Tuple[float, int]]:
        try:
            st = os.stat(path)
            return (st.st_mtime, st.st_size)
        except OSError:
            return None

    def _load(self, config: Dict[str, Any]) -> None:
        """Parse and index a subscriber database dict (raises on error)"""
        if not isinstance(config, dict):
            raise SubscriberConfigError('Subscriber file must contain a JSON object')

        enforcement = config.get('enforcement', {})
        mode = enforcement.get('mode', 'disabled')
        if mode not in VALID_MODES:
            raise SubscriberConfigError(
                f"Invalid enforcement mode '{mode}' (valid: {', '.join(VALID_MODES)})")
        reload_interval = enforcement.get('reload_interval', 60)
        if not isinstance(reload_interval, (int, float)) or reload_interval < 0:
            raise SubscriberConfigError('enforcement.reload_interval must be a number >= 0')

        fleets: List[Fleet] = []
        exact: Dict[int, Tuple[Fleet, Optional[SubscriberEntry]]] = {}
        ranges: List[Tuple[int, int, Fleet]] = []

        for i, fdict in enumerate(config.get('fleets', [])):
            context = f"fleet[{i}]"
            if not isinstance(fdict, dict):
                raise SubscriberConfigError(f'{context}: must be an object')
            name = fdict.get('name')
            if not name or not isinstance(name, str):
                raise SubscriberConfigError(f'{context}: missing required "name"')
            context = f"fleet '{name}'"

            fleet = Fleet(
                name=name,
                description=fdict.get('description', ''),
                enabled=bool(fdict.get('enabled', True)),
                talkgroups=_parse_tg_list(fdict.get('talkgroups'), context),
                slot1_talkgroups=_parse_tg_list(fdict.get('slot1_talkgroups'), context),
                slot2_talkgroups=_parse_tg_list(fdict.get('slot2_talkgroups'), context),
            )

            for rid in fdict.get('ids', []):
                rid = _parse_radio_id(rid, context)
                if rid in exact:
                    LOGGER.warning(f"Subscriber ACL: radio {rid} in {context} already claimed "
                                   f"by fleet '{exact[rid][0].name}' - first definition wins")
                    continue
                fleet.ids.add(rid)
                exact[rid] = (fleet, None)

            for r in fdict.get('id_ranges', []):
                if (not isinstance(r, list)) or len(r) != 2:
                    raise SubscriberConfigError(f'{context}: id_ranges entries must be [start, end]')
                start = _parse_radio_id(r[0], context)
                end = _parse_radio_id(r[1], context)
                if start > end:
                    raise SubscriberConfigError(f'{context}: invalid range {start}-{end} (start > end)')
                fleet.id_ranges.append((start, end))
                ranges.append((start, end, fleet))

            for j, sdict in enumerate(fdict.get('subscribers', [])):
                scontext = f"{context} subscriber[{j}]"
                if not isinstance(sdict, dict):
                    raise SubscriberConfigError(f'{scontext}: must be an object')
                rid = _parse_radio_id(sdict.get('id'), scontext)
                entry = SubscriberEntry(
                    radio_id=rid,
                    alias=str(sdict.get('alias', '')),
                    enabled=bool(sdict.get('enabled', True)),
                    talkgroups=_parse_tg_list(sdict.get('talkgroups'), scontext),
                )
                if rid in exact and exact[rid][1] is not None:
                    LOGGER.warning(f"Subscriber ACL: radio {rid} listed twice "
                                   f"(fleets '{exact[rid][0].name}' and '{name}') - first wins")
                    continue
                fleet.subscribers[rid] = entry
                # Explicit entry overrides bulk id membership for the index
                exact[rid] = (fleet, entry)

            fleets.append(fleet)

        # Sort ranges for binary search and warn about overlaps between fleets
        ranges.sort(key=lambda r: (r[0], r[1]))
        max_end, max_fleet = -1, None
        for start, end, fleet in ranges:
            if start <= max_end and fleet is not max_fleet:
                LOGGER.warning(f"Subscriber ACL: ID ranges overlap between fleet "
                               f"'{max_fleet.name}' and fleet '{fleet.name}' near {start} - "
                               f"lookups favor the later-starting range")
            if end > max_end:
                max_end, max_fleet = end, fleet

        # Commit only after full successful parse (atomic swap for reloads)
        self.mode = mode
        self.reload_interval = reload_interval
        self.fleets = fleets
        self._exact = exact
        self._ranges = ranges
        self._range_starts = [r[0] for r in ranges]

    # ---------------------------------------------------------------- reload

    def maybe_reload(self) -> bool:
        """
        Reload the subscriber file if it changed on disk.

        Called periodically from the event loop. A file that fails to parse
        is logged and ignored - the last known-good database stays active.

        Returns True if a new database was loaded.
        """
        if not self._source_path:
            return False

        sig = self._stat_file(self._source_path)
        if sig is None:
            # File vanished - keep serving the loaded database
            if self._file_sig is not None:
                LOGGER.error(f'Subscriber ACL: file {self._source_path} is missing - '
                             f'keeping last loaded database')
                self._file_sig = None
            return False
        if sig == self._file_sig:
            return False

        try:
            with open(self._source_path, 'r') as f:
                config = json.load(f)
            self._load(config)
            self._file_sig = sig
            stats = self.get_stats()
            LOGGER.info(f"Subscriber ACL reloaded from {self._source_path}: "
                        f"mode={self.mode}, {stats['fleets']} fleets, "
                        f"{stats['explicit_subscribers']} explicit subscribers, "
                        f"{stats['id_range_span']} IDs in ranges")
            return True
        except (OSError, json.JSONDecodeError, SubscriberConfigError) as e:
            # Remember the bad signature so we don't re-log every interval,
            # but keep the previous good database active.
            self._file_sig = sig
            LOGGER.error(f'Subscriber ACL: reload of {self._source_path} failed, '
                         f'keeping last known-good database: {e}')
            return False

    # ---------------------------------------------------------------- lookup

    def lookup(self, radio_id: int) -> Optional[Tuple[Fleet, Optional[SubscriberEntry]]]:
        """Find the fleet (and explicit entry, if any) for a radio ID"""
        hit = self._exact.get(radio_id)
        if hit:
            return hit

        # Binary search the range index: rightmost range starting <= radio_id
        idx = bisect_right(self._range_starts, radio_id) - 1
        while idx >= 0:
            start, end, fleet = self._ranges[idx]
            if start <= radio_id <= end:
                return (fleet, None)
            # Ranges are sorted by start; an earlier range can still cover us
            # only if it's wider (nested/overlapping). Walk back while possible.
            if end < radio_id and start < radio_id:
                idx -= 1
                continue
            break
        return None

    def get_alias(self, radio_id: int) -> str:
        """Best-known alias for a radio ID ('' if none configured)"""
        hit = self._exact.get(radio_id)
        if hit and hit[1]:
            return hit[1].alias
        return ''

    # ----------------------------------------------------------------- check

    def check_access(self, radio_id: int, dst_id: int, slot: int,
                     call_type: str = 'group') -> AccessDecision:
        """
        Authorize one transmission. Called once per stream start.

        Args:
            radio_id: Source subscriber radio ID
            dst_id: Destination TGID (group call) or radio ID (private call)
            slot: Timeslot 1 or 2
            call_type: 'group' or 'private' - talkgroup permissions only
                       apply to group calls

        Returns:
            AccessDecision. In 'permissive' mode allowed is always True and
            would_deny flags the violation; in 'enforce' mode allowed is the
            real verdict.
        """
        if self.mode == 'disabled':
            return AccessDecision(allowed=True, reason=REASON_DISABLED)

        enforcing = (self.mode == 'enforce')

        hit = self.lookup(radio_id)
        if hit is None:
            return AccessDecision(allowed=not enforcing, reason=REASON_UNKNOWN,
                                  would_deny=True)

        fleet, entry = hit
        alias = entry.alias if entry else ''

        if not fleet.enabled:
            return AccessDecision(allowed=not enforcing, reason=REASON_FLEET_DISABLED,
                                  would_deny=True, fleet=fleet.name, alias=alias)

        if entry and not entry.enabled:
            return AccessDecision(allowed=not enforcing, reason=REASON_SUBSCRIBER_DISABLED,
                                  would_deny=True, fleet=fleet.name, alias=alias)

        # Talkgroup authorization applies to group calls only; a private
        # call's destination is a radio ID, not a talkgroup.
        if call_type == 'group':
            allowed_tgs = self._effective_talkgroups(fleet, entry, slot)
            if allowed_tgs is not None and dst_id not in allowed_tgs:
                return AccessDecision(allowed=not enforcing, reason=REASON_TG_DENIED,
                                      would_deny=True, fleet=fleet.name, alias=alias)

        return AccessDecision(allowed=True, reason=REASON_AUTHORIZED,
                              fleet=fleet.name, alias=alias)

    @staticmethod
    def _effective_talkgroups(fleet: Fleet, entry: Optional[SubscriberEntry],
                              slot: int) -> Optional[set]:
        """
        Resolve the talkgroup set that applies to this transmission.
        Precedence: subscriber override > fleet per-slot list > fleet list.
        None means no restriction (allow all).
        """
        if entry and entry.talkgroups is not None:
            return entry.talkgroups
        slot_tgs = fleet.slot1_talkgroups if slot == 1 else fleet.slot2_talkgroups
        if slot_tgs is not None:
            return slot_tgs
        return fleet.talkgroups

    # ----------------------------------------------------------------- stats

    def get_stats(self) -> dict:
        """Summary statistics for logging and the dashboard"""
        range_span = sum(end - start + 1 for start, end, _ in self._ranges)
        return {
            'mode': self.mode,
            'fleets': len(self.fleets),
            'explicit_subscribers': sum(len(f.subscribers) for f in self.fleets),
            'explicit_ids': len(self._exact),
            'id_ranges': len(self._ranges),
            'id_range_span': range_span,
        }
