# Part 90 Operation Guide

HBlink4 can operate as the core of a **commercial (FCC Part 90) DMR network**.
Where amateur networks are open by design - any radio with a valid ID can key
up - a Part 90 system is a *closed* network: only radios provisioned by the
system operator may transmit, each customer's traffic stays on that customer's
talkgroups, and every call is accounted for.

Two features provide this layer, both off by default and fully independent:

| Feature | What it gives you |
|---------|-------------------|
| **Subscriber access control** | Per-radio authorization against a fleet map: unknown radios blocked, stolen radios disabled remotely, talkgroups restricted per fleet or per radio |
| **Call Detail Records (CDR)** | One machine-readable record per call for billing, capacity planning, and incident review, plus a record of every denied access attempt |

Both operate at **stream start** (once per transmission, not per packet), so
they add no per-packet forwarding cost and do not affect audio latency.

These checks are in addition to - not instead of - the existing repeater-level
controls. The two layers answer different questions:

- **Repeater configuration** (`repeater_configurations`): *which repeaters may
  connect, and which talkgroups may exist on each repeater/slot.*
- **Subscriber access control** (`subscribers.json`): *which radios may
  transmit, and on which talkgroups.*

A transmission must pass both layers to be forwarded.

---

## Subscriber Access Control

### Enabling

In `config/config.json`:

```json
"global": {
    "subscriber_access": {
        "enabled": true,
        "file": "config/subscribers.json"
    }
}
```

Then create the subscriber database:

```bash
cp config/subscribers_sample.json config/subscribers.json
```

If `enabled` is `true` and the file is missing or invalid, HBlink4 **refuses to
start** - a closed network must never come up unprotected by accident.

### The subscriber file

```json
{
    "enforcement": {
        "mode": "permissive",
        "reload_interval": 60
    },
    "fleets": [
        {
            "name": "Acme Delivery",
            "description": "Acme Delivery Co. - dispatch and drivers",
            "enabled": true,
            "ids": [3120001],
            "id_ranges": [[3121000, 3121099]],
            "talkgroups": [101, 102],
            "slot1_talkgroups": null,
            "slot2_talkgroups": null,
            "subscribers": [
                {"id": 3121010, "alias": "Truck 10"},
                {"id": 3121050, "alias": "Truck 50 (stolen)", "enabled": false}
            ]
        }
    ]
}
```

#### `enforcement`

| Key | Values | Meaning |
|-----|--------|---------|
| `mode` | `disabled` | Checks off entirely. Identical to pre-Part 90 behavior. |
| | `permissive` | Checks run; violations are **logged and written to the CDR but traffic passes**. Use this while building the fleet map on a live system. |
| | `enforce` | Violations are **denied**. Production mode for a closed network. |
| `reload_interval` | seconds | How often the file is checked for changes (`0` disables hot reload). Changing `reload_interval` itself requires a restart. |

#### Fleets

A **fleet** is a customer or agency. It owns radio IDs (individually via `ids`,
in bulk via `id_ranges`) and defines which talkgroups those radios may use.

| Key | Type | Meaning |
|-----|------|---------|
| `name` | string, required | Fleet name (appears in logs, CDRs, and events) |
| `description` | string | Free-form notes |
| `enabled` | boolean | `false` suspends the entire fleet (e.g. lapsed account) |
| `ids` | list of ints | Individual radio IDs belonging to this fleet |
| `id_ranges` | list of `[start, end]` | Inclusive ID blocks belonging to this fleet |
| `talkgroups` | list of ints or `null` | TGs this fleet may use. `null` = all, `[]` = none |
| `slot1_talkgroups` / `slot2_talkgroups` | list or `null` | Optional per-slot override of `talkgroups` |
| `subscribers` | list | Explicitly-listed radios (below) |

#### Subscribers

An explicitly-listed radio. Listing a radio here authorizes it even if its ID
is outside the fleet's `ids`/`id_ranges`, and lets you attach metadata:

| Key | Type | Meaning |
|-----|------|---------|
| `id` | int, required | DMR radio ID |
| `alias` | string | Human name ("Truck 10", "Gate 2") - appears in logs and CDRs |
| `enabled` | boolean | `false` blocks this one radio (stolen, retired, non-payment) |
| `talkgroups` | list or `null` | Per-radio TG override. `null` = inherit from fleet |

#### Authorization logic

For each new transmission (group call), in order:

1. Radio ID looked up: explicit subscriber entry first, then fleet `ids`, then
   `id_ranges` (binary search). Not found → `unknown_subscriber`.
2. Fleet disabled → `fleet_disabled`. Radio disabled → `subscriber_disabled`.
3. Talkgroup check, using the first defined of: subscriber `talkgroups` →
   fleet `slot1_talkgroups`/`slot2_talkgroups` (by slot) → fleet `talkgroups`.
   `null` at every level means unrestricted. Failure → `talkgroup_denied`.

Private calls (when enabled in a future release) skip step 3 - their
destination is a radio, not a talkgroup.

### Hot reload

The file is re-read automatically when it changes on disk (checked every
`reload_interval` seconds). This means you can, with **zero downtime**:

- Add a new customer fleet or a new radio
- Disable a stolen radio: set `"enabled": false` on its entry and save
- Move from `permissive` to `enforce` mode

A file that fails to parse is logged and **ignored** - the last known-good
database stays active, so a typo can never open (or brick) the network.

### Recommended rollout

1. Start in **`permissive`** mode with your best-guess fleet map.
2. Let it run. Every violation is logged (`Subscriber ACL PERMISSIVE (would
   deny)`) and written to the CDR as a `deny` record with `"enforced": false`.
3. Review the deny records; add legitimate radios you missed:
   ```bash
   jq -r 'select(.type=="deny") | [.src_id, .dst_id, .reason] | @tsv' logs/cdr/cdr-*.jsonl | sort | uniq -c | sort -rn
   ```
4. When the deny stream is quiet, switch `mode` to **`enforce`** and save. The
   change takes effect within `reload_interval` seconds.

---

## Call Detail Records

### Enabling

```json
"global": {
    "cdr": {
        "enabled": true,
        "directory": "logs/cdr",
        "retention_days": 90
    }
}
```

### Format

One JSON object per line (JSONL), one file per day: `logs/cdr/cdr-YYYYMMDD.jsonl`.
Files older than `retention_days` are deleted automatically (`0` keeps
everything). Records are flushed to disk as they are written, so they survive
an unclean shutdown.

**`call` record** - written when a transmission ends (exactly one per call,
from the receiving repeater's perspective):

```json
{"type":"call","start":1754140000.123,"end":1754140004.523,"start_iso":"2025-08-02T08:26:40",
 "duration":4.4,"src_id":3121010,"alias":"Truck 10","fleet":"Acme Delivery",
 "dst_id":101,"slot":1,"call_type":"group","repeater_id":312001,
 "repeater_callsign":"WQAB123","packets":264,"targets":3,"end_reason":"terminator"}
```

| Field | Meaning |
|-------|---------|
| `start` / `end` / `duration` | Epoch timestamps and seconds of airtime |
| `src_id`, `alias`, `fleet` | Who transmitted (alias/fleet from the subscriber database, `null` if unknown) |
| `dst_id`, `slot`, `call_type` | Where the call went |
| `repeater_id`, `repeater_callsign` | The repeater that received the call from RF |
| `packets` | DMR packets in the stream (~55/sec of voice) |
| `targets` | How many repeaters the call was forwarded to |
| `end_reason` | `terminator`, `fast_terminator`, `timeout`, `repeater_disconnect`, or `shutdown` |

**`deny` record** - written when the subscriber ACL blocks (or, in permissive
mode, flags) a transmission:

```json
{"type":"deny","time":1754140100.5,"time_iso":"2025-08-02T08:28:20","src_id":3129999,
 "alias":null,"fleet":null,"dst_id":101,"slot":1,"repeater_id":312001,
 "reason":"unknown_subscriber","enforced":true}
```

### Working with CDRs

Airtime per fleet for a day (billing):

```bash
jq -r 'select(.type=="call") | [.fleet // "UNKNOWN", .duration] | @tsv' logs/cdr/cdr-20250802.jsonl \
  | awk -F'\t' '{a[$1]+=$2} END {for (f in a) printf "%-25s %8.1f s\n", f, a[f]}'
```

Busiest talkgroups:

```bash
jq -r 'select(.type=="call") | .dst_id' logs/cdr/cdr-*.jsonl | sort | uniq -c | sort -rn | head
```

Every denied attempt today:

```bash
jq -c 'select(.type=="deny")' logs/cdr/cdr-$(date +%Y%m%d).jsonl
```

---

## Dashboard events

The server emits an `access_denied` event (in addition to the CDR record) for
each blocked or flagged stream, carrying `src_id`, `dst_id`, `slot`,
`repeater_id`, `reason`, `fleet`, `alias`, and `enforced`. The bundled
dashboard currently ignores unknown event types; a future dashboard release
will surface these in the Recent Events panel.

---

## Part 90 roadmap

Planned on top of this foundation (see also `docs/TODO.md`):

- **Private (unit-to-unit) call routing** - subscriber-to-subscriber calls
  with target discovery via the user cache. The ACL API already accepts
  private calls; routing is tracked in TODO item 1.
- **Emergency call priority** - detect the emergency service option in the
  voice LC and pre-empt non-emergency traffic on contended slots.
- **Encrypted-call awareness** - Part 90 permits encryption; flag
  privacy-enabled calls in stream events and CDRs (traffic already passes
  transparently today).
- **Dashboard fleet view** - per-fleet activity and deny feed using the
  `access_denied` event and CDR data.
