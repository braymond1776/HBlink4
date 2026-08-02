"""
Unit tests for the Part 90 subscriber access control module
"""

import json
import os
import tempfile
import unittest

from hblink4.subscribers import (
    SubscriberACL, SubscriberConfigError,
    REASON_AUTHORIZED, REASON_DISABLED, REASON_UNKNOWN,
    REASON_SUBSCRIBER_DISABLED, REASON_FLEET_DISABLED, REASON_TG_DENIED,
)


def make_config(mode='enforce'):
    """A representative two-fleet database used by most tests"""
    return {
        'enforcement': {'mode': mode, 'reload_interval': 60},
        'fleets': [
            {
                'name': 'Acme Delivery',
                'enabled': True,
                'ids': [3120001],
                'id_ranges': [[3121000, 3121099]],
                'talkgroups': [101, 102],
                'subscribers': [
                    {'id': 3121010, 'alias': 'Truck 10'},
                    {'id': 3121050, 'alias': 'Stolen', 'enabled': False},
                    {'id': 3121060, 'alias': 'Restricted', 'talkgroups': [101]},
                    {'id': 3129999, 'alias': 'Outside Range'},
                ],
            },
            {
                'name': 'Public Works',
                'enabled': True,
                'id_ranges': [[3122000, 3122499]],
                'slot1_talkgroups': [201, 202],
                'slot2_talkgroups': [209],
            },
            {
                'name': 'Old Fleet',
                'enabled': False,
                'ids': [3123001],
            },
        ],
    }


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.acl = SubscriberACL(make_config())

    def test_exact_id(self):
        fleet, entry = self.acl.lookup(3120001)
        self.assertEqual(fleet.name, 'Acme Delivery')
        self.assertIsNone(entry)

    def test_range_id(self):
        fleet, entry = self.acl.lookup(3121042)
        self.assertEqual(fleet.name, 'Acme Delivery')
        self.assertIsNone(entry)

    def test_range_boundaries(self):
        self.assertIsNotNone(self.acl.lookup(3121000))
        self.assertIsNotNone(self.acl.lookup(3121099))
        self.assertIsNone(self.acl.lookup(3120999))
        self.assertIsNone(self.acl.lookup(3121100))

    def test_explicit_subscriber(self):
        fleet, entry = self.acl.lookup(3121010)
        self.assertEqual(fleet.name, 'Acme Delivery')
        self.assertEqual(entry.alias, 'Truck 10')

    def test_explicit_subscriber_outside_ranges(self):
        """Listing a subscriber authorizes it even outside fleet ID ranges"""
        fleet, entry = self.acl.lookup(3129999)
        self.assertEqual(fleet.name, 'Acme Delivery')
        self.assertEqual(entry.alias, 'Outside Range')

    def test_unknown(self):
        self.assertIsNone(self.acl.lookup(1234567))

    def test_second_fleet_range(self):
        fleet, _ = self.acl.lookup(3122250)
        self.assertEqual(fleet.name, 'Public Works')

    def test_nested_ranges(self):
        """Binary search walks back to wider ranges when nested"""
        acl = SubscriberACL({
            'enforcement': {'mode': 'enforce'},
            'fleets': [
                {'name': 'Wide', 'id_ranges': [[100, 500]]},
                {'name': 'Narrow', 'id_ranges': [[200, 300]]},
            ],
        })
        self.assertEqual(acl.lookup(250)[0].name, 'Narrow')
        self.assertEqual(acl.lookup(150)[0].name, 'Wide')
        self.assertEqual(acl.lookup(400)[0].name, 'Wide')
        self.assertIsNone(acl.lookup(600))

    def test_get_alias(self):
        self.assertEqual(self.acl.get_alias(3121010), 'Truck 10')
        self.assertEqual(self.acl.get_alias(3121042), '')
        self.assertEqual(self.acl.get_alias(999), '')


class TestCheckAccessEnforce(unittest.TestCase):
    def setUp(self):
        self.acl = SubscriberACL(make_config('enforce'))

    def test_authorized(self):
        d = self.acl.check_access(3121010, 101, 1)
        self.assertTrue(d.allowed)
        self.assertEqual(d.reason, REASON_AUTHORIZED)
        self.assertEqual(d.fleet, 'Acme Delivery')
        self.assertEqual(d.alias, 'Truck 10')
        self.assertFalse(d.would_deny)

    def test_unknown_subscriber_denied(self):
        d = self.acl.check_access(1234567, 101, 1)
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, REASON_UNKNOWN)
        self.assertTrue(d.would_deny)

    def test_disabled_subscriber_denied(self):
        d = self.acl.check_access(3121050, 101, 1)
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, REASON_SUBSCRIBER_DISABLED)
        self.assertEqual(d.alias, 'Stolen')

    def test_disabled_fleet_denied(self):
        d = self.acl.check_access(3123001, 101, 1)
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, REASON_FLEET_DISABLED)
        self.assertEqual(d.fleet, 'Old Fleet')

    def test_talkgroup_denied(self):
        d = self.acl.check_access(3121010, 999, 1)
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, REASON_TG_DENIED)

    def test_subscriber_tg_override(self):
        """Per-subscriber TG list overrides the fleet list"""
        self.assertTrue(self.acl.check_access(3121060, 101, 1).allowed)
        # 102 is in the fleet list but not the subscriber override
        self.assertFalse(self.acl.check_access(3121060, 102, 1).allowed)

    def test_per_slot_talkgroups(self):
        self.assertTrue(self.acl.check_access(3122001, 201, 1).allowed)
        self.assertFalse(self.acl.check_access(3122001, 201, 2).allowed)
        self.assertTrue(self.acl.check_access(3122001, 209, 2).allowed)
        self.assertFalse(self.acl.check_access(3122001, 209, 1).allowed)

    def test_private_call_skips_tg_check(self):
        """Private call destination is a radio ID, not a talkgroup"""
        d = self.acl.check_access(3121010, 3122001, 1, call_type='private')
        self.assertTrue(d.allowed)
        self.assertEqual(d.reason, REASON_AUTHORIZED)

    def test_private_call_still_checks_identity(self):
        d = self.acl.check_access(3121050, 3122001, 1, call_type='private')
        self.assertFalse(d.allowed)
        self.assertEqual(d.reason, REASON_SUBSCRIBER_DISABLED)

    def test_no_tg_restriction_allows_all(self):
        acl = SubscriberACL({
            'enforcement': {'mode': 'enforce'},
            'fleets': [{'name': 'Open', 'ids': [42]}],
        })
        self.assertTrue(acl.check_access(42, 12345, 1).allowed)

    def test_empty_tg_list_denies_all(self):
        acl = SubscriberACL({
            'enforcement': {'mode': 'enforce'},
            'fleets': [{'name': 'Muted', 'ids': [42], 'talkgroups': []}],
        })
        self.assertFalse(acl.check_access(42, 1, 1).allowed)


class TestModes(unittest.TestCase):
    def test_disabled_mode_allows_everything(self):
        acl = SubscriberACL(make_config('disabled'))
        d = acl.check_access(1234567, 999, 1)
        self.assertTrue(d.allowed)
        self.assertEqual(d.reason, REASON_DISABLED)
        self.assertFalse(d.would_deny)

    def test_permissive_mode_allows_but_flags(self):
        acl = SubscriberACL(make_config('permissive'))
        d = acl.check_access(1234567, 999, 1)
        self.assertTrue(d.allowed)
        self.assertTrue(d.would_deny)
        self.assertEqual(d.reason, REASON_UNKNOWN)

    def test_permissive_authorized_not_flagged(self):
        acl = SubscriberACL(make_config('permissive'))
        d = acl.check_access(3121010, 101, 1)
        self.assertTrue(d.allowed)
        self.assertFalse(d.would_deny)


class TestValidation(unittest.TestCase):
    def test_invalid_mode(self):
        with self.assertRaises(SubscriberConfigError):
            SubscriberACL({'enforcement': {'mode': 'bogus'}})

    def test_invalid_range_order(self):
        with self.assertRaises(SubscriberConfigError):
            SubscriberACL({'enforcement': {'mode': 'enforce'},
                           'fleets': [{'name': 'X', 'id_ranges': [[500, 100]]}]})

    def test_invalid_radio_id(self):
        with self.assertRaises(SubscriberConfigError):
            SubscriberACL({'enforcement': {'mode': 'enforce'},
                           'fleets': [{'name': 'X', 'ids': [0]}]})
        with self.assertRaises(SubscriberConfigError):
            SubscriberACL({'enforcement': {'mode': 'enforce'},
                           'fleets': [{'name': 'X', 'ids': [0x1000000]}]})

    def test_invalid_talkgroups(self):
        with self.assertRaises(SubscriberConfigError):
            SubscriberACL({'enforcement': {'mode': 'enforce'},
                           'fleets': [{'name': 'X', 'talkgroups': ['abc']}]})

    def test_missing_fleet_name(self):
        with self.assertRaises(SubscriberConfigError):
            SubscriberACL({'enforcement': {'mode': 'enforce'}, 'fleets': [{}]})

    def test_missing_subscriber_id(self):
        with self.assertRaises(SubscriberConfigError):
            SubscriberACL({'enforcement': {'mode': 'enforce'},
                           'fleets': [{'name': 'X', 'subscribers': [{'alias': 'no id'}]}]})

    def test_duplicate_id_first_wins(self):
        acl = SubscriberACL({
            'enforcement': {'mode': 'enforce'},
            'fleets': [
                {'name': 'First', 'ids': [42]},
                {'name': 'Second', 'ids': [42]},
            ],
        })
        self.assertEqual(acl.lookup(42)[0].name, 'First')

    def test_empty_config_valid(self):
        acl = SubscriberACL({})
        self.assertEqual(acl.mode, 'disabled')
        self.assertEqual(acl.get_stats()['fleets'], 0)


class TestReload(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, 'subscribers.json')

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write(self, config):
        with open(self.path, 'w') as f:
            json.dump(config, f)

    def _touch(self, offset):
        """Force a distinct mtime (filesystem mtime granularity can be coarse)"""
        st = os.stat(self.path)
        os.utime(self.path, (st.st_atime, st.st_mtime + offset))

    def test_from_file_and_reload(self):
        self._write(make_config('permissive'))
        acl = SubscriberACL.from_file(self.path)
        self.assertEqual(acl.mode, 'permissive')

        # No change on disk -> no reload
        self.assertFalse(acl.maybe_reload())

        # Change mode and add a fleet
        cfg = make_config('enforce')
        cfg['fleets'].append({'name': 'New Fleet', 'ids': [777]})
        self._write(cfg)
        self._touch(5)

        self.assertTrue(acl.maybe_reload())
        self.assertEqual(acl.mode, 'enforce')
        self.assertEqual(acl.lookup(777)[0].name, 'New Fleet')

    def test_bad_reload_keeps_old_database(self):
        self._write(make_config('enforce'))
        acl = SubscriberACL.from_file(self.path)

        with open(self.path, 'w') as f:
            f.write('{ this is not json')
        self._touch(5)

        self.assertFalse(acl.maybe_reload())
        # Old database still active
        self.assertEqual(acl.mode, 'enforce')
        self.assertEqual(acl.lookup(3121010)[0].name, 'Acme Delivery')

        # And the bad file is not retried/re-logged until it changes again
        self.assertFalse(acl.maybe_reload())

        # Fixing the file recovers
        self._write(make_config('permissive'))
        self._touch(10)
        self.assertTrue(acl.maybe_reload())
        self.assertEqual(acl.mode, 'permissive')

    def test_missing_file_keeps_old_database(self):
        self._write(make_config('enforce'))
        acl = SubscriberACL.from_file(self.path)
        os.unlink(self.path)
        self.assertFalse(acl.maybe_reload())
        self.assertEqual(acl.lookup(3121010)[0].name, 'Acme Delivery')


class TestStats(unittest.TestCase):
    def test_stats(self):
        acl = SubscriberACL(make_config())
        stats = acl.get_stats()
        self.assertEqual(stats['mode'], 'enforce')
        self.assertEqual(stats['fleets'], 3)
        self.assertEqual(stats['explicit_subscribers'], 4)
        self.assertEqual(stats['id_ranges'], 2)
        self.assertEqual(stats['id_range_span'], 100 + 500)


if __name__ == '__main__':
    unittest.main()
