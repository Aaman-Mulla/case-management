#!/usr/bin/env python3
import os

from app import create_app


def _resolve_config_name():
    config_name = os.getenv('APP_CONFIG')
    if config_name:
        return config_name
    return os.getenv('FLASK_ENV', 'production')


app = create_app(_resolve_config_name())


if __name__ == '__main__':
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '5001'))
    threads = int(os.getenv('WEB_THREADS', '8'))

    try:
        from waitress import serve
    except ImportError as exc:
        raise RuntimeError('waitress is required for production serving. Install requirements.txt') from exc

    serve(app, host=host, port=port, threads=threads)
