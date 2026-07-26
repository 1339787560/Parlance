#!/usr/bin/env python3
"""Control client for the infoServer Launcher.

Sends a single JSON-RPC 2.0 request to the running Launcher's control socket
(Named Pipe on Windows, UDS on POSIX) and prints the response as JSON.

The socket address must match the Launcher's ControlServer (see run.py).
Wire format is multiprocessing.connection; this client is the canonical front-end.

Usage:
    python ctl_client.py reload
    python ctl_client.py status
    python ctl_client.py quit
    python ctl_client.py start
    python ctl_client.py stop
    python ctl_client.py <method> --params '{"k": "v"}'

Exit codes:
    0  success (response carries no JSON-RPC error)
    1  connection / usage error (Launcher not running, bad params)
    2  JSON-RPC error response received
"""

import argparse
import json
import os
import sys
from multiprocessing.connection import Client

CTL_PIPE_WIN = r"\\.\pipe\infoserver_ctl"
CTL_SOCKET_POSIX = "/tmp/infoserver_ctl.sock"


def _ctl_address():
    if os.name == "nt":
        return (CTL_PIPE_WIN, "AF_PIPE")
    return (CTL_SOCKET_POSIX, "AF_UNIX")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="infoServer control client")
    parser.add_argument("method",
                        help="JSON-RPC method: reload|quit|status|start|stop")
    parser.add_argument("--params", default="{}",
                        help="JSON object params (default {})")
    parser.add_argument("--id", type=int, default=1,
                        help="request id (default 1)")
    args = parser.parse_args(argv)

    try:
        params = json.loads(args.params) if args.params else {}
    except json.JSONDecodeError as e:
        print(f"invalid --params JSON: {e}", file=sys.stderr)
        return 1

    address, family = _ctl_address()
    request = {
        "jsonrpc": "2.0",
        "id": args.id,
        "method": args.method,
        "params": params,
    }

    try:
        conn = Client(address, family=family)
    except (FileNotFoundError, ConnectionRefusedError, OSError) as e:
        print(f"cannot connect to control socket {address}: {e}", file=sys.stderr)
        print("is the infoServer Launcher running?", file=sys.stderr)
        return 1

    try:
        conn.send(request)
        response = conn.recv()
    except EOFError:
        print("connection closed before response", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"recv failed: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass

    print(json.dumps(response, ensure_ascii=False))
    if isinstance(response, dict) and "error" in response:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
