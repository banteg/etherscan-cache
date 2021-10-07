from collections import defaultdict
from functools import wraps
from itertools import cycle
from threading import Lock

import diskcache
import requests
import toml
from eth_utils import to_checksum_address
from fastapi import FastAPI, HTTPException

app = FastAPI()
cache = diskcache.Cache("cache", statistics=True, size_limit=10e9)
config = toml.load(open("config.toml"))
keys = {explorer: cycle(config[explorer]["keys"]) for explorer in config}


def stampede(f):
    locks = defaultdict(Lock)

    @wraps(f)
    def inner(*args, **kwargs):
        key = f.__cache_key__(*args, **kwargs)
        with locks[key]:
            return f(*args, **kwargs)

    return inner


@stampede
@cache.memoize()
def get_from_upstream(explorer, module, action, address):
    print(f"fetching {explorer} {address}")
    resp = requests.get(
        config[explorer]["url"],
        params={
            "module": module,
            "action": action,
            "address": address,
            "apiKey": next(keys[explorer]),
        },
    )
    resp.raise_for_status()
    return resp.json()


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

    return get_from_upstream(explorer, module, action, address)


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
