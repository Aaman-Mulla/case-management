#!/usr/bin/env python3
import os
import socket
import subprocess
import sys

from app import create_app


def _resolve_config_name():
    config_name = os.getenv('APP_CONFIG')
    if config_name:
        return config_name
    return os.getenv('FLASK_ENV', 'production')


def _get_ethernet_ip():
    """Auto-detect the Ethernet adapter's IPv4 address (Windows)."""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             "(Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Ethernet*' "
             "| Where-Object { $_.PrefixOrigin -ne 'WellKnown' } "
             "| Select-Object -First 1).IPAddress"],
            capture_output=True, text=True, timeout=10
        )
        ip = result.stdout.strip()
        if ip:
            return ip
    except Exception:
        pass
    # Fallback: connect a UDP socket to an external address to find the default route IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


app = create_app(_resolve_config_name())


if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '5001'))
    threads = int(os.getenv('WEB_THREADS', '8'))

    try:
        from waitress import serve
    except ImportError as exc:
        raise RuntimeError('waitress is required for production serving. Install requirements.txt') from exc

    lan_ip = _get_ethernet_ip()
    print(f'  * Ethernet IP detected: {lan_ip}')
    print(f'  * Server live at: http://{lan_ip}:{port}')
    print(f'  * Binding on {host}:{port} (threads={threads})')
    sys.stdout.flush()

    serve(app, host=host, port=port, threads=threads)
