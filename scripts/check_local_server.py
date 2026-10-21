"""Exit 0 for our running server, 1 for a free port, 2 for a conflict."""

import argparse
import json
import socket
from urllib.request import urlopen


def check_server(kind, port):
    try:
        with urlopen(f'http://127.0.0.1:{port}/', timeout=5) as response:
            body = response.read(65536).decode('utf-8')
        if kind == 'backend':
            matches = json.loads(body).get('message') == 'NBA Fantasy Analytics API'
        else:
            matches = '/@vite/client' in body and '/src/main.jsx' in body
        if matches:
            print(f'{kind.capitalize()} is already running on port {port}; reusing it.')
            return 0
    except (OSError, ValueError):
        pass
    try:
        with socket.socket() as probe:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(('127.0.0.1', port))
    except OSError:
        print(f'Port {port} is occupied or unavailable. Cannot start {kind}.')
        return 2
    return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=('backend', 'frontend'))
    parser.add_argument('port', type=int)
    args = parser.parse_args()
    raise SystemExit(check_server(args.kind, args.port))
