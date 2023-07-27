from collections import defaultdict
from functools import wraps
from itertools import cycle
from threading import Lock

import os
import diskcache
import requests
import toml
from cachetools.func import ttl_cache
from eth_utils import to_checksum_address
from fastapi import FastAPI, HTTPException


if SENTRY_DSN := os.environ.get("SENTRY_DSN"):
    import sentry_sdk
    sentry_sdk.init(SENTRY_DSN)
    
app = FastAPI()
cache = diskcache.Cache("cache", statistics=True, size_limit=10e9)
config = toml.load(open("config.toml"))
keys = {explorer: cycle(config[explorer]["keys"]) for explorer in config}

class ContractNotVerified(HTTPException):
    ...


def stampede(f):
    locks = defaultdict(Lock)

    @wraps(f)
    def inner(*args, **kwargs):
        key = f.__cache_key__(*args, **kwargs)
        with locks[key]:
            return f(*args, **kwargs)

    return inner


@ttl_cache(ttl=60*60)  # Caches api response for one hour, lets us ensure bad responses aren't disk cached
def weak_cache(explorer, module, action, address):
    print(f"fetching {explorer} {address}")
    resp = requests.get(
        config[explorer]["url"],
        params={
            "module": module,
            "action": action,
            "address": address,
            "apiKey": next(keys[explorer]),
        },
        headers={ "User-Agent": "Mozilla/5.0" }
    )
    resp.raise_for_status()
    return resp.json()
    
    
@stampede
@cache.memoize()
def get_from_upstream(explorer, module, action, address):
    resp = weak_cache(explorer, module, action, address)
    # NOTE: raise an exception here if the contract isn't verified
    is_verified = False if resp["result"] == 'Contract source code not verified' else bool(resp["result"][0].get("SourceCode"))
    if not is_verified:
        raise ContractNotVerified(404, 'contract source code not verified')
    return resp


@app.get("/{explorer}/api")
def cached_api(explorer: str, module: str, action: str, address: str):
    if explorer not in config:
        raise HTTPException(400, "explorer not supported")

    if module not in ["contract"]:
        raise HTTPException(400, "module not supported")

    if action not in ["getsourcecode", "getabi"]:
        raise HTTPException(400, "action not supported")

    try:
        address = to_checksum_address(address)
    except ValueError:
        raise HTTPException(400, "invalid address")

    try:
        return get_from_upstream(explorer, module, action, address)
    except ContractNotVerified:
        return weak_cache(explorer, module, action, address)


@app.delete("/{explorer}/api")
def invalidate(explorer: str, address: str):
    deleted = 0

    for key in cache.iterkeys():
        if (key[1], key[4]) == (explorer, address):
            deleted += bool(cache.delete(key))
    
    return {'deleted': deleted}


@app.get("/stats")
def cache_stats():
    hits, misses = cache.stats()
    count = cache._sql("select count(*) from Cache").fetchone()
    return {
        "hits": hits,
        "misses": misses,
        "count": count[0],
        "size": cache.volume(),
    }
