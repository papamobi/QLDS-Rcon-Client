# QLDS RCON Client

A Python 3 RCON client for Quake Live dedicated servers.

Based on the original `zmq_rcon.py` (Python 2) supplied with the Quake Live Dedicated Server (QLDS). Rewritten for Python 3 with added features: interactive mode with live server output, command history, color output, multi-host config file support, auto-status and minqlx shortcuts.

---

## Requirements

```
pip install pyzmq
```

---

## Usage

**Interactive mode (recommended):**
```bash
python3 qlrcon.py --host tcp://YOUR_SERVER_IP:RCON_PORT --password YOUR_RCON_PASSWORD
```

**Single command:**
```bash
python3 qlrcon.py --host tcp://YOUR_SERVER_IP:RCON_PORT --password YOUR_RCON_PASSWORD --cmd map_restart
```

**With config file (no flags needed):**
```bash
python3 qlrcon.py
```

---

## Options

| Flag | Description |
|------|-------------|
| `--host` | Server RCON address in format `tcp://IP:PORT` |
| `--password` | RCON password (`zmq_rcon_password` in server.cfg) |
| `--cmd` | Single command to run, then exit |
| `--timeout` | Seconds to wait for response (default: 3) |
| `--identity` | Custom ZMQ socket identity (default: random UUID) |
| `--profile` | Named profile from `~/.qlrcon` to use (default: default) |
| `--verbose` | Show ZMQ connection events |
| `--no-color` | Disable colored output |
| `--no-status` | Skip automatic status command on connect |
| `--live` | Stream live server output (chat, player connects etc.) |

---

## Server Requirements

The following must be set in your `server.cfg` or through command line for RCON to work:

```
set zmq_rcon_enable "1"
set zmq_rcon_port "YOUR_RCON_PORT"
set zmq_rcon_password "YOUR_PASSWORD"
```

---

## Config File (`~/.qlrcon`)

Store defaults so you don't need to pass flags every time:

```
host=tcp://YOUR_SERVER_IP:RCON_PORT
password=YOUR_RCON_PASSWORD
timeout=3
# live=true
```

CLI arguments always override config file values.

### Multi-host support

Use named profiles to manage multiple servers in one config file:

```
[default]
password=YOUR_RCON_PASSWORD
timeout=3

[server1]
host=tcp://YOUR_SERVER_IP:RCON_PORT

[server2]
host=tcp://YOUR_OTHER_SERVER_IP:RCON_PORT
password=DIFFERENT_PASSWORD
```

Settings from `[default]` are inherited by all profiles unless overridden. Connect to a specific server with `--profile`:

```bash
python3 qlrcon.py --profile server1
python3 qlrcon.py --profile server2
```

---

## Interactive Mode

- Connects and automatically sends `status` to show current server state
- Type any QL server command and press Enter
- Up/down arrows cycle through command history (saved to `~/.qlrcon_history`)
- Response lines are timestamped and color-coded
- Quake color codes (`^1`, `^2` etc.) are stripped from output
- Minqlx commands can be typed directly as in game chat (including all minqlx admin cmds) e.g. `!teamsize`, `!kick`
- Type `/live` to toggle live server output on/off during the session
- Type `exit`, `disconnect` or Ctrl+C to close
* Note: `quit` is a server command and will shut the server down

---

## Examples

```bash
# Connect to server
python3 qlrcon.py --host tcp://YOUR_SERVER_IP:RCON_PORT --password YOUR_RCON_PASSWORD

# Connect with live server output
python3 qlrcon.py --host tcp://YOUR_SERVER_IP:RCON_PORT --password YOUR_RCON_PASSWORD --live

# Send a single command
python3 qlrcon.py --host tcp://YOUR_SERVER_IP:RCON_PORT --password YOUR_RCON_PASSWORD --cmd map_restart

# Connect without auto-status
python3 qlrcon.py --host tcp://YOUR_SERVER_IP:RCON_PORT --password YOUR_RCON_PASSWORD --no-status

# Using config file
echo "host=tcp://YOUR_SERVER_IP:RCON_PORT" >> ~/.qlrcon
echo "password=YOUR_RCON_PASSWORD" >> ~/.qlrcon
python3 qlrcon.py

# Connect using a named profile
python3 qlrcon.py --profile server1

# Scripting / non-interactive (positional args)
python3 qlrcon.py YOUR_SERVER_IP RCON_PORT YOUR_PASSWORD map_restart
```
