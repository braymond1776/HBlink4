# IpswichSuite

**IpswichSuite** is a DMR network server for commercial (FCC Part 90) and amateur radio systems, by **Ipswich River Labs, LLC**. It speaks the HomeBrew DMR protocol used by MMDVM-based repeaters and hotspots, operating as an endpoint network server with granular per-repeater control.

IpswichSuite is a GPLv3 fork of [HBlink4](https://github.com/n0mjs710/HBlink4) by Cortney T. Buffington, N0MJS — see [License](#license) and [Acknowledgments](#acknowledgments).

Built for **closed commercial (Part 90) operation**: per-radio subscriber authorization against a fleet map, remote lockout of stolen or delinquent radios, per-fleet talkgroup isolation, and Call Detail Records for billing and audit. See the [Part 90 Operation Guide](docs/part90.md).

## Architecture

IpswichSuite focuses on being an efficient **endpoint network server** with the following design principles:

- **Per-repeater routing rules** using TS/TGID tuples for precise call handling
- **Individual repeater management** rather than server-level "system" groupings
- **Direct source connectivity** without multi-hop relay complexity
- **Granular per-repeater control and monitoring**
- **Tightly integrated web dashboard** - Real-time monitoring with WebSocket updates

## Features

- **Part 90 subscriber access control** - fleet map with per-radio authorization, stolen-radio lockout, hot reload without restart
- **Call Detail Records (CDR)** - daily JSONL call accounting for billing, capacity planning, and security audit
- **Native dual-stack IPv4/IPv6 support** - Simultaneous listening on both protocols for maximum compatibility
- Modern asyncio-based Python implementation with type hints
- JSON-based configuration
- **Tightly integrated web dashboard** - Real-time monitoring with modern look and feel (see [Dashboard Documentation](dashboard/README.md))
- **Stream tracking with immediate DMR terminator detection (~60ms)**
- **Real-time duration counter with 1-second updates**
- **Two-tier stream end detection (immediate terminator + timeout fallback)**
- **User routing cache for efficient private call routing**
- Pattern-based repeater configuration and blacklisting
- Per-slot transmission management

## Installation

> **⚠️ IMPORTANT**: Clone and run IpswichSuite as the same user account. The systemd service files are configured to run as the user who owns the installation directory. The dashboard writes files for persistence across restarts and needs write access as well.

1. Clone this repository:
```bash
git clone https://github.com/braymond1776/HBlink4.git ipswichsuite
cd ipswichsuite
```

2. Create a virtual environment and activate it:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install requirements:
```bash
pip install -r requirements.txt
```

## Configuration

Copy the sample configuration file and modify it for your needs:
```bash
cp config/config_sample.json config/config.json
```

For a Part 90 (closed) system, also create the subscriber database:
```bash
cp config/subscribers_sample.json config/subscribers.json
```

See the [Configuration Guide](docs/configuration.md) for complete documentation of all settings.

## Running

### Production (systemd services)
For production deployments with automatic startup, see [SYSTEMD.md](SYSTEMD.md).

### Development
```bash
# Start all services together
./run_all.sh

# Or start services separately:
python3 run.py              # IpswichSuite server
python3 run_dashboard.py    # Web dashboard (in another terminal)
```

Access the dashboard at http://localhost:8080. See [Dashboard Documentation](dashboard/README.md) for features and configuration.

## Documentation

Comprehensive documentation is available in the `docs/` directory:

- **[Configuration Guide](docs/configuration.md)** - Complete configuration reference with all settings explained
- **[Part 90 Operation Guide](docs/part90.md)** - Subscriber access control and Call Detail Records for commercial systems
- **[Dashboard README](dashboard/README.md)** - Dashboard features and usage
- **[Systemd Service Installation](SYSTEMD.md)** - Production deployment with automatic startup
- **[Connecting Repeaters](docs/connecting.md)** - How to connect repeaters to IpswichSuite
- **[Stream Tracking](docs/stream_tracking.md)** - How DMR transmission streams are managed
- **[Hang Time](docs/hang_time.md)** - Preventing conversation interruption
- **[Protocol Specification](docs/protocol.md)** - HomeBrew DMR protocol details
- **[Integration Guide](docs/integration.md)** - Using IpswichSuite as a module
- **[Logging](docs/logging.md)** - Log management and rotation

Historical design documents from the project's HBlink4 lineage are preserved unmodified in [docs/history](docs/history/).

## Support

IpswichSuite is developed by Ipswich River Labs, LLC. Bug reports with logs and reproduction steps are welcome via GitHub issues. Commercial support, hosted network service, and Part 90 deployment assistance are offered separately by Ipswich River Labs.

## Contributing

Contributions are welcome via Pull Request. Please discuss substantial features before building them — use a feature branch named for the change. By contributing you agree your contribution is licensed under GPLv3.

## License

IpswichSuite is free software licensed under the **GNU GPLv3** — see the [LICENSE](LICENSE) file.

- Copyright (C) 2016-2025 Cortney T. Buffington, N0MJS (HBlink3/HBlink4, from which this project is derived)
- Copyright (C) 2025-2026 Ipswich River Labs, LLC (IpswichSuite modifications and additions)

Complete corresponding source for this program is this repository. Modifications relative to upstream HBlink4 are recorded in the git history.

**Trademark notice**: "IpswichSuite", "Ipswich River Labs", and the IpswichSuite logo identify Ipswich River Labs, LLC. The GPLv3 licenses the software's source code; it does not grant rights to these names or marks. Redistributed or modified versions must not present themselves as IpswichSuite or as products of Ipswich River Labs.

## Acknowledgments

- [HBlink4](https://github.com/n0mjs710/HBlink4) and HBlink3 by Cort Buffington, N0MJS — the foundation this project is built on
- The MMDVM and DMR community
