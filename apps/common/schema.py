def drop_trailing_slash_duplicates(endpoints, **kwargs):
    """
    Every API route also matches with a trailing slash (see apps.common.routers). Document
    each operation once, in the canonical slash-less form the frontend contract uses.
    """
    seen: set[tuple[str, str]] = set()
    result = []
    for path, path_regex, method, callback in endpoints:
        canonical = path.rstrip("/") if path.startswith("/api/") else path
        if (canonical, method) in seen:
            continue
        seen.add((canonical, method))
        result.append((canonical, path_regex, method, callback))
    return result
