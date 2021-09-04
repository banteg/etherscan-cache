import math
from itertools import cycle

import diskcache
import requests
import toml
from eth_utils import to_checksum_address
from fastapi import FastAPI, HTTPException

app = FastAPI()
cache = diskcache.Cache("cache", statistics=True, size_limit=10e9)
config = toml.load(open("config.toml"))
keys = {explorer: cycle(config[explorer]["keys"]) for explorer in config}


@diskcache.memoize_stampede(cache, expire=math.inf)
def get_from_upstream(explorer, module, action, address):
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
