#!/usr/bin/env python3
# Version: 1.5
#
# Changelog:
# 1.5 - Added session logging to file (optional --log flag, /log toggle, log=true in config)
# 1.4 - Do not print "Connected" message if no response from server, just shows warning
#       Color tweaks
# 1.3 - Added named profile support in ~/.qlrcon config file (--profile flag)
#       Settings from [default] section are inherited by all profiles
# 1.2 - Stripped literal \n from broadcast messages
#       Improved grey color visibility for ZMQ events and verbose output
# 1.1 - Added sv_hostname and net_port auto-send on connect (before status)
#       Verbose mode now shows auto-sending messages for all auto commands
#       Filtered zmq RCON command echo lines from output
#       Fixed echo filter to work in both single and interactive mode
# 1.0 - Initial release
"""
QLDS RCON Client
=========================
Based on the original zmq_rcon.py (Python 2) supplied with Quake Live Dedicated Server (QLDS).
Rewritten for Python 3 with added features: interactive mode with live server output,
command history, color output, multi-host config file support, auto-status and minqlx shortcuts.


USAGE
-----
Interactive mode (recommended):
  python3 qlrcon.py --host tcp://YOUR_SERVER_IP:RCON_PORT --password YOUR_RCON_PASSWORD

Single command:
  python3 qlrcon.py --host tcp://YOUR_SERVER_IP:RCON_PORT --password YOUR_RCON_PASSWORD --cmd status

With config file (no flags needed):
  python3 qlrcon.py

OPTIONS
-------
  --host       Server RCON address in format tcp://IP:PORT
               e.g. tcp://192.168.1.1:28965
               Requires in server.cfg:
                 set zmq_rcon_enable "1"
                 set zmq_rcon_port "YOUR_RCON_PORT"
  --password   RCON password (zmq_rcon_password in server.cfg)
  --cmd        Single command to run, then exit
  --timeout    Seconds to wait for response (default: 3)
  --identity   Custom ZMQ socket identity (default: random UUID)
  --verbose    Show connection events
  --profile    Named profile from ~/.qlrcon to use (default: default)
  --no-color   Disable colored output
  --no-status  Skip automatic status command on connect
  --live       Stream live server output (chat, player connects etc.)
               Type '/live' during session to toggle on/off
  --log        Enable logging to ~/.qlrcon_logs/<host>.log (5MB rotating, 3 backups)
               Type '/log' during session to toggle on/off

CONFIG FILE (~/.qlrcon)
-----------------------
Store defaults so you don't need to pass flags every time:

  host=tcp://YOUR_SERVER_IP:RCON_PORT
  password=YOUR_RCON_PASSWORD
  timeout=3

CLI arguments always override config file values.

INTERACTIVE MODE
----------------
  - Connects and automatically sends 'status' to show current server state
  - Type any QL server command and press Enter
  - Up/down arrows cycle through command history (saved to ~/.qlrcon_history)
  - Type '/live' to toggle live server output on/off during the session
  - Response lines are timestamped and color-coded
  - QL color codes (^1, ^2 etc.) are stripped from output
  - You can execute minqlx commands directly from the terminal (including admin commands),
    as in game e.g. !teamsize, !kick etc.
  - Type 'exit', 'disconnect' or Ctrl+C to close
  - Use --no-status to skip the automatic status on connect

EXAMPLES
--------
  # Connect to server
  python3 qlrcon.py --host tcp://YOUR_SERVER_IP:RCON_PORT --password YOUR_RCON_PASSWORD

  # Send a single command without entering interactive mode
  python3 qlrcon.py --host tcp://YOUR_SERVER_IP:RCON_PORT --password YOUR_RCON_PASSWORD --cmd map_restart

  # Connect without auto-status
  python3 qlrcon.py --host tcp://YOUR_SERVER_IP:RCON_PORT --password YOUR_RCON_PASSWORD --no-status

  # Using config file
  echo "host=tcp://YOUR_SERVER_IP:RCON_PORT" >> ~/.qlrcon
  echo "password=YOUR_RCON_PASSWORD" >> ~/.qlrcon
  python3 qlrcon.py

  # Scripting / non-interactive (positional args):
  python3 qlrcon.py YOUR_SERVER_IP RCON_PORT YOUR_PASSWORD map_restart
"""

import sys
import time
import argparse
import uuid
import zmq
import readline
import threading
import queue
import logging
import logging.handlers
from datetime import datetime

POLL_TIMEOUT = 100  # ms

# ── Terminal colors ───────────────────────────────────────────────────────────

class C:
    RESET   = '\033[0m'
    RED     = '\033[31m'
    GREEN   = '\033[32m'
    YELLOW  = '\033[33m'
    CYAN    = '\033[36m'
    GREY    = '\033[37m'
    BOLD    = '\033[1m'

def supports_color():
    return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

USE_COLOR = supports_color()

def colorize(text, color):
    return color + text + C.RESET if USE_COLOR else text

def timestamp():
    return colorize(datetime.now().strftime('%H:%M:%S'), C.GREY)

def print_response(text):
    ts = timestamp()
    for line in text.splitlines():
        clean = strip_ql_colors(line)
        if clean.strip():
            print(f"{ts} {colorize(clean, C.GREEN)}")

def print_info(text):
    print(colorize(text, C.CYAN))

def print_error(text):
    print(colorize(text, C.RED), file=sys.stderr)

def print_prompt():
    return colorize('rcon', C.YELLOW) + colorize('> ', C.GREY) if USE_COLOR else 'rcon> '


# ── Config file ───────────────────────────────────────────────────────────────

def load_config(profile='default'):
    """Load ~/.qlrcon config file. Supports named profiles with [profile] sections."""
    import os
    config = {}
    config_file = os.path.expanduser('~/.qlrcon')
    if not os.path.exists(config_file):
        return config

# ── ZMQ ──────────────────────────────────────────────────────────────────────

def build_socket(ctx, password, identity, verbose=False):
    socket  = ctx.socket(zmq.DEALER)
    monitor = socket.get_monitor_socket(zmq.EVENT_ALL)
    if verbose:
        print(colorize(f'Setting username and password for access.', C.GREY))
        print(colorize(f'UUID: {identity}', C.GREY))
    socket.plain_username = b"rcon"
    socket.plain_password = password.encode()
    socket.zap_domain     = b"rcon"
    socket.setsockopt(zmq.IDENTITY, identity.encode())
    socket.setsockopt(zmq.LINGER, 0)
    return socket, monitor

ZMQ_EVENTS = {
    zmq.EVENT_CONNECTED:          'CONNECTED',
    zmq.EVENT_CONNECT_DELAYED:    'CONNECT_DELAYED',
    zmq.EVENT_CONNECT_RETRIED:    'CONNECT_RETRIED',
    zmq.EVENT_DISCONNECTED:       'DISCONNECTED',
    zmq.EVENT_CLOSED:             'CLOSED',
    zmq.EVENT_MONITOR_STOPPED:    'MONITOR_STOPPED',
    zmq.EVENT_HANDSHAKE_SUCCEEDED: 'HANDSHAKE_SUCCEEDED',
    zmq.EVENT_HANDSHAKE_FAILED_NO_DETAIL: 'HANDSHAKE_FAILED',
    zmq.EVENT_HANDSHAKE_FAILED_PROTOCOL:  'HANDSHAKE_FAILED_PROTOCOL',
    zmq.EVENT_HANDSHAKE_FAILED_AUTH:      'HANDSHAKE_FAILED_AUTH',
}

def read_monitor(monitor, verbose=False):
    """Read pending monitor events, print if verbose. Returns event_id of last event or None."""
    last = None
    try:
        while True:
            event_msg = monitor.recv(zmq.NOBLOCK)
            event_id  = int.from_bytes(event_msg[:2], 'little')
            endpoint  = monitor.recv(zmq.NOBLOCK).decode('utf-8', errors='replace')
            name      = ZMQ_EVENTS.get(event_id, f'EVENT_{event_id}')
            if verbose:
                print(colorize(f'[zmq] {name} — {endpoint}', C.GREY))
            last = event_id
    except zmq.Again:
        pass
    return last

def wait_for_connection(socket, monitor, host, timeout=5, verbose=False):
    socket.connect(host)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if monitor.poll(POLL_TIMEOUT):
            try:
                event_msg = monitor.recv(zmq.NOBLOCK)
                event_id  = int.from_bytes(event_msg[:2], 'little')
                endpoint  = monitor.recv(zmq.NOBLOCK).decode('utf-8', errors='replace')
                name      = ZMQ_EVENTS.get(event_id, f'EVENT_{event_id}')
                if verbose:
                    print(colorize(f'[zmq] {name} — {endpoint}', C.GREY))
                if event_id == zmq.EVENT_CONNECTED:
                    if verbose:
                        print(colorize('Registering with the server.', C.GREY))
                    socket.send(b"register")
                    return True
            except zmq.Again:
                pass
    return False

def strip_ql_colors(text):
    """Strip Quake Live color codes like ^1 ^2 ^7 etc from text."""
    import re
    text = re.sub(r'\^[0-9a-zA-Z]', '', text)
    text = text.replace('\\n', '')
    return text

def collect_frames(socket, timeout_ms=3000):
    """Collect all frames and join them — QL sends player rows as many small frames."""
    deadline = time.time() + (timeout_ms / 1000)
    frames   = []
    while time.time() < deadline:
        event = socket.poll(POLL_TIMEOUT)
        if event == 0:
            if time.time() > deadline:
                break
            continue
        while True:
            try:
                msg = socket.recv(zmq.NOBLOCK)
                frames.append(msg.decode('utf-8', errors='replace'))
            except zmq.Again:
                break
    result = "".join(frames)
    # Filter out server echo of register command
    lines = [l for l in result.splitlines(keepends=True) if ": register" not in l and "zmq RCON command from" not in l]
    return "".join(lines)

def flush_socket(socket):
    """Discard any buffered frames that arrived while we were waiting for input."""
    while True:
        try:
            socket.recv(zmq.NOBLOCK)
        except zmq.Again:
            break

def send_command(socket, command, timeout_ms=3000):
    socket.send(command.encode())
    return collect_frames(socket, timeout_ms)

# ── Modes ─────────────────────────────────────────────────────────────────────

def mode_single(host, password, command, timeout, identity, verbose):
    ctx    = zmq.Context()
    socket, monitor = build_socket(ctx, password, identity, verbose)
    if verbose:
        print_info(f"Connecting to {host}...")

    if not wait_for_connection(socket, monitor, host, timeout, verbose):
        print_error("Could not connect")
        sys.exit(1)

    if verbose:
        print_info(f"Sending: {command}")

    result = send_command(socket, command, timeout * 1000)
    print(result, end='')

    monitor.close()
    socket.close()
    ctx.term()

def mode_interactive(host, password, timeout, identity, verbose, auto_status=True, live=False, log=False):
    import os, queue
    history_file = os.path.expanduser('~/.qlrcon_history')
    try:
        readline.read_history_file(history_file)
    except FileNotFoundError:
        pass
    readline.set_history_length(500)

    # Set up rotating file logger
    import os
    log_dir  = os.path.expanduser('~/.qlrcon_logs')
    log_name = host.replace('tcp://', '').replace(':', '_').replace('/', '_') + '.log'
    log_path = os.path.join(log_dir, log_name)
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger('qlrcon')
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'
    )
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    logger.addHandler(handler)

    log_state = {'enabled': log}

    def logwrite(msg):
        if log_state['enabled']:
            logger.info(msg)

    ctx    = zmq.Context()
    socket, monitor = build_socket(ctx, password, identity, verbose)
    print_info(f"Connecting to {host}...")
    if not wait_for_connection(socket, monitor, host, timeout, verbose):
        print_error("Could not connect.")
        sys.exit(1)

    # Send register and check if server responds
    socket.send(b"register")
    responding = socket.poll(2000)
    if responding:
        logwrite(f'Connected to {host}')
        print_info("Connected. Type 'exit', 'disconnect' or Ctrl+C to close.")
        print(colorize("Note: 'quit' is a server command and will shut the server down.", C.GREY))
        if live:
            print(colorize("Live mode ON — server output streaming. Type '/live' to toggle.", C.CYAN))
        if log:
            print(colorize(f"Logging ON → {log_path}", C.CYAN))
    else:
        print_error("Warning: Server not responding. Please verify your RCON port and password.")
        print_info("Type 'exit' or Ctrl+C to close.")
    print()

    # Two queues: live_queue for streaming output, resp_queue for command responses
    live_queue = queue.Queue()
    resp_queue = queue.Queue()
    state = {'live': live, 'stop': False, 'waiting': False}

    def socket_reader():
        """Reads all socket frames and routes them appropriately."""
        while not state['stop']:
            try:
                if socket.poll(50):
                    while True:
                        try:
                            msg = socket.recv(zmq.NOBLOCK)
                            text = msg.decode('utf-8', errors='replace')
                            if ': register' in text or 'zmq RCON command from' in text:
                                continue
                            if state['waiting']:
                                resp_queue.put(msg)
                            else:
                                live_queue.put(msg)
                        except zmq.Again:
                            break
            except Exception:
                break

    reader = threading.Thread(target=socket_reader, daemon=True)
    reader.start()

    def live_printer():
        """Continuously print live frames when live mode is on."""
        while not state['stop']:
            if state['live'] and not state['waiting']:
                try:
                    msg = live_queue.get(timeout=0.1)
                    text = strip_ql_colors(msg.decode('utf-8', errors='replace'))
                    for line in text.splitlines():
                        if line.strip():
                            print(f'\r{timestamp()} {colorize(line, C.GREEN)}')
                            print(print_prompt(), end='', flush=True)
                            logwrite(line)
                except queue.Empty:
                    pass
            else:
                time.sleep(0.05)

    printer = threading.Thread(target=live_printer, daemon=True)
    printer.start()

    def get_response(timeout_ms=3000):
        state['waiting'] = True
        # Drain live queue into resp queue first
        while not live_queue.empty():
            try: resp_queue.put(live_queue.get_nowait())
            except queue.Empty: break
        frames = []
        deadline = time.time() + (timeout_ms / 1000)
        while time.time() < deadline:
            try:
                msg = resp_queue.get(timeout=0.05)
                frames.append(msg.decode('utf-8', errors='replace'))
                deadline = min(deadline, time.time() + 0.3)
            except queue.Empty:
                if frames:
                    break
        state['waiting'] = False
        result = ''.join(frames)
        return strip_ql_colors(result)

    def drain_queues():
        for q in (live_queue, resp_queue):
            while not q.empty():
                try: q.get_nowait()
                except queue.Empty: break

    # Auto-send status
    if auto_status and responding:
        for cmd in [b'sv_hostname', b'net_port', b'status']:
            if verbose:
                print(colorize(f'Auto-sending: {cmd.decode()}', C.GREY))
            logwrite(f'>>> {cmd.decode()}')
            socket.send(cmd)
            result = get_response(timeout * 1000)
            if result.strip():
                print_response(result)
                logwrite(result.strip())

    try:
        while True:
            try:
                cmd = input(print_prompt()).strip()
            except EOFError:
                break

            if not cmd:
                continue

            # Auto-prefix minqlx commands
            if cmd.startswith('!'):
                cmd = 'qlx ' + cmd
                if verbose:
                    print(colorize(f'minqlx command → {cmd}', C.GREY))

            if cmd.lower() in ('exit', 'disconnect'):
                print(colorize('\nDisconnected.', C.CYAN))
                break

            # Toggle live mode
            if cmd.lower() == '/live':
                state['live'] = not state['live']
                status = 'ON' if state['live'] else 'OFF'
                print(colorize(f'Live mode {status}', C.CYAN))
                continue

            # Toggle logging
            if cmd.lower() == '/log':
                log_state['enabled'] = not log_state['enabled']
                status = 'ON' if log_state['enabled'] else 'OFF'
                print(colorize(f'Logging {status}' + (f' → {log_path}' if log_state["enabled"] else ''), C.CYAN))
                continue

            read_monitor(monitor, verbose)

            if not state['live']:
                drain_queues()

            if verbose:
                print(colorize(f'Sending command: {cmd}', C.GREY))

            logwrite(f'>>> {cmd}')
            socket.send(cmd.encode())
            result = get_response(timeout * 1000)
            read_monitor(monitor, verbose)

            if result.strip():
                print_response(result)
                logwrite(result.strip())
            else:
                print(colorize('(no response)', C.GREY))

    except KeyboardInterrupt:
        logwrite('Disconnected.')
        print(colorize('\nDisconnected.', C.CYAN))
    finally:
        state['stop'] = True
        try:
            readline.write_history_file(history_file)
        except Exception:
            pass
        monitor.close()
        socket.close()
        ctx.term()


def main():
    # Legacy positional args mode (also supports non-interactive scripting):
    # rcon.py <host> <port> <password> <command> [timeout]
    if len(sys.argv) >= 5 and not sys.argv[1].startswith('--'):
        host     = sys.argv[1]
        port     = int(sys.argv[2])
        password = sys.argv[3]
        command  = sys.argv[4]
        timeout  = int(sys.argv[5]) if len(sys.argv) > 5 else 3
        mode_single(f"tcp://{host}:{port}", password, command, timeout, uuid.uuid1().hex, verbose=False)
        return

    # Load config file first, CLI args override
    # Pre-parse --profile before argparse so we can load the right config section
    import sys as _sys
    _profile = 'default'
    for _i, _a in enumerate(_sys.argv):
        if _a == '--profile' and _i + 1 < len(_sys.argv):
            _profile = _sys.argv[_i + 1]
    cfg = load_config(_profile)

    parser = argparse.ArgumentParser(
        description='Tr1ckHouse QL RCON client',
        epilog='Config file: ~/.qlrcon (key=value, one per line). Keys: host, password, timeout, identity'
    )
    parser.add_argument('--host',     default=cfg.get('host'),     help='Server RCON address e.g. tcp://SERVER_IP:RCON_PORT')
    parser.add_argument('--password', default=cfg.get('password'), help='RCON password')
    parser.add_argument('--cmd',      default=None,                help='Single command to run and exit (omit for interactive mode with auto-status)')
    parser.add_argument('--timeout',  type=int, default=int(cfg.get('timeout', 3)), help='Timeout in seconds (default: 3)')
    parser.add_argument('--identity', default=cfg.get('identity', uuid.uuid1().hex), help='ZMQ socket identity (default: random UUID)')
    parser.add_argument('--verbose',  action='store_true', help='Show connection events')
    parser.add_argument('--profile',    default='default',   help='Config profile to use from ~/.qlrcon (default: default)')
    parser.add_argument('--no-color',   action='store_true', help='Disable colored output')
    parser.add_argument('--no-status',  action='store_true', help='Skip auto status on connect')
    parser.add_argument('--live',        action='store_true', help='Show live server output (chat, kills, events) as it arrives')
    parser.add_argument('--log',         action='store_true', help='Enable logging to ~/.qlrcon_logs/<host>.log')
    args = parser.parse_args()

    if args.no_color:
        global USE_COLOR
        USE_COLOR = False

    # Allow live=true and log=true in config file
    if not args.live and cfg.get('live', '').lower() in ('true', '1', 'yes'):
        args.live = True
    if not args.log and cfg.get('log', '').lower() in ('true', '1', 'yes'):
        args.log = True

    if not args.host:
        print_error("Error: --host is required (or set 'host' in ~/.qlrcon)")
        sys.exit(1)
    if not args.password:
        print_error("Error: --password is required (or set 'password' in ~/.qlrcon)")
        sys.exit(1)

    if args.cmd:
        mode_single(args.host, args.password, args.cmd, args.timeout, args.identity, args.verbose)
    else:
        mode_interactive(args.host, args.password, args.timeout, args.identity, args.verbose, not args.no_status, args.live, args.log)

if __name__ == "__main__":
    main()
