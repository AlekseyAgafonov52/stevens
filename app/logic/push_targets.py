"""Web Push: только доверенные сервисы, без redirect и скрытых proxy."""
import base64
import ipaddress
import socket
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import ec
import requests


def allowed_endpoint(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        return (url.scheme == "https" and url.port in (None, 443) and not url.username
                and not url.password and not url.fragment and not any(c.isspace() for c in value)
                and (host in {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"}
                     or host.endswith(".notify.windows.com") or host.endswith(".push.apple.com")))
    except ValueError:
        return False


def valid_keys(keys: object) -> bool:
    if not isinstance(keys, dict):
        return False
    try:
        values = []
        for name, limit in (("p256dh", 200), ("auth", 100)):
            raw = keys.get(name)
            if not isinstance(raw, str) or not 1 <= len(raw) <= limit:
                return False
            values.append(base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True))
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), values[0])
        return len(values[1]) == 16
    except (ValueError, TypeError):
        return False


class PushSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False

    def request(self, method, url, params=None, data=None, headers=None, cookies=None,
                files=None, auth=None, timeout=None, allow_redirects=True, proxies=None,
                hooks=None, stream=None, verify=None, cert=None, json=None):
        if not allowed_endpoint(url):
            raise ValueError("invalid_subscription")
        host = urlsplit(url).hostname
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("invalid_subscription")
        # Ограниченный список доменов принадлежит провайдерам push; TLS проверяется requests.
        return super().request(method, url, params=params, data=data, headers=headers,
                               cookies=cookies, files=files, auth=auth, timeout=timeout,
                               allow_redirects=False, proxies={}, hooks=hooks, stream=stream,
                               verify=True, cert=cert, json=json)
