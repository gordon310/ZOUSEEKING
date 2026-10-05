"""Stable PWA discovery URLs must revalidate, including on the consumer host."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_all_static_hosts_revalidate_service_worker_and_manifest():
    config = (ROOT / 'deploy/nginx/default.conf').read_text()
    static_hosts = [block for block in config.split('server {') if 'root /usr/share/nginx/html-' in block]
    assert len(static_hosts) == 3
    for host in static_hosts:
        worker = re.search(r'location\s*=\s*/sw\.js\s*\{([^{}]*)\}', host)
        assert worker, 'sw.js must override the generic immutable JavaScript rule'
        assert 'no-cache' in worker.group(1)
        assert 'immutable' not in worker.group(1)
        manifest = re.search(r'location\s+~\*\s+\\\.webmanifest\$\s*\{([^{}]*)\}', host)
        assert manifest
        assert 'application/manifest+json' in manifest.group(1)
        assert 'no-cache' in manifest.group(1)
        assert 'immutable' not in manifest.group(1)
        assert 'public, max-age=31536000, immutable' in host, 'ordinary versioned assets keep their existing policy'
