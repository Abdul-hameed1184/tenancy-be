from django.conf import settings


def client_ip(request) -> str | None:
    """
    Client IP, trusting X-Forwarded-For only for the configured number of proxies.

    Taking the left-most X-Forwarded-For entry blindly would let any client spoof its IP
    (and dodge per-IP throttles). With NUM_PROXIES=n, the n-th address from the right is the
    one the outermost trusted proxy saw.
    """
    meta = getattr(request, "META", {})
    num_proxies = settings.REST_FRAMEWORK.get("NUM_PROXIES")
    forwarded = meta.get("HTTP_X_FORWARDED_FOR")
    if num_proxies and forwarded:
        addresses = [a.strip() for a in forwarded.split(",") if a.strip()]
        if addresses:
            return addresses[-min(num_proxies, len(addresses))]
    return meta.get("REMOTE_ADDR") or None


def user_agent(request) -> str:
    return getattr(request, "META", {}).get("HTTP_USER_AGENT", "")[:256]
