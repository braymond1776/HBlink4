# IpswichSuite Systemd Service Installation

This directory contains systemd service files for running IpswichSuite and its dashboard as system services.

## Service Files

- `ipswichsuite.service` - Main IpswichSuite DMR server
- `ipswichsuite-dash.service` - Web dashboard (depends on ipswichsuite.service)

## Installation

### 1. Install the service files

Copy the service files to systemd's system directory:

```bash
sudo cp ipswichsuite.service /etc/systemd/system/
sudo cp ipswichsuite-dash.service /etc/systemd/system/
```

### 2. Reload systemd

Tell systemd to reload its configuration:

```bash
sudo systemctl daemon-reload
```

### 3. Enable services (optional)

To start the services automatically at boot:

```bash
sudo systemctl enable ipswichsuite
sudo systemctl enable ipswichsuite-dash
```

### 4. Start the services

```bash
sudo systemctl start ipswichsuite
sudo systemctl start ipswichsuite-dash
```

## Service Management

### Check service status

```bash
sudo systemctl status ipswichsuite
sudo systemctl status ipswichsuite-dash
```

### View logs

```bash
# View logs for IpswichSuite
sudo journalctl -u ipswichsuite -f

# View logs for dashboard
sudo journalctl -u ipswichsuite-dash -f

# View last 100 lines
sudo journalctl -u ipswichsuite -n 100
```

### Stop services

```bash
sudo systemctl stop ipswichsuite
sudo systemctl stop ipswichsuite-dash
```

### Restart services

```bash
sudo systemctl restart ipswichsuite
sudo systemctl restart ipswichsuite-dash
```

### Disable autostart

```bash
sudo systemctl disable ipswichsuite
sudo systemctl disable ipswichsuite-dash
```

## Configuration

The service files are configured to:
- Run as user `ipswich` in group `ipswich`
- Use the Python virtual environment at `/opt/ipswichsuite/venv`
- Automatically restart on failure (after 10 seconds)
- Log to systemd journal (view with `journalctl`)
- Start after network is available
- Dashboard starts after and depends on IpswichSuite

### Customization

If you need to modify the services (different user, paths, etc.), edit the files before copying them:

1. Edit `ipswichsuite.service` and/or `ipswichsuite-dash.service`
2. Change `User=`, `Group=`, `WorkingDirectory=`, or `ExecStart=` as needed
3. Copy to `/etc/systemd/system/`
4. Run `sudo systemctl daemon-reload`

## Security Features

Both services include security hardening:
- `NoNewPrivileges=true` - Prevents privilege escalation
- `PrivateTmp=true` - Isolates /tmp directory

## Troubleshooting

### Service won't start

Check the status and logs:
```bash
sudo systemctl status ipswichsuite
sudo journalctl -u ipswichsuite -n 50
```

Common issues:
- Virtual environment not found: Check path in `ExecStart=`
- Permission errors: Ensure user/group are correct
- Config file errors: Check IpswichSuite configuration files
- Port conflicts: Another service using the same ports

### Dashboard can't connect to IpswichSuite

1. Ensure IpswichSuite is running: `sudo systemctl status ipswichsuite`
2. Check dashboard config points to correct socket/host
3. Check logs: `sudo journalctl -u ipswichsuite-dash -n 50`

## Notes

- The dashboard service has `Wants=ipswichsuite.service`, so it will start after IpswichSuite
- Both services have `Restart=always` for automatic recovery
- Logs are sent to systemd journal, not file-based logging
- Services run with the same privileges as the configured service user
