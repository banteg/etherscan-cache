from collections import defaultdict
from functools import wraps
from itertools import cycle
from threading import Lock

import os
import diskcache
import requests
import toml
import json
from cachetools.func import ttl_cache
from eth_utils import to_checksum_address
from fastapi import FastAPI, HTTPException
from typing import Optional
from constructor_args import do_on_chain_lookup, get_creation_tx, get_creation_code


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
    if action == "getsourcecode":
        is_verified = bool(resp["result"][0].get("SourceCode"))
    elif action == "getabi":
        is_verified = not resp["result"] == 'Contract source code not verified'
    else:
        raise NotImplementedError(action)
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

@app.get("/{explorer}/constructor_args/{address}")
def constructor_args(
  explorer: str,
  address: str,
  on_chain_lookup: bool=False,
  creation_tx_hash: Optional[str]=None,
  bytecode: Optional[str]=None):
  """
  Returns the constructor args for a contract provided by ``address``.

  By default, it tries to get the constructor args from the explorer by calling
  its api.

  For doing on-chain lookups instead, the ``on_chain_lookup`` param can be set to ``True``.
  On-chain lookup will also be done as a fallback if explorer based lookups fail:

  1. get the creation_code from the creation tx
  2. compare it with the passed ``bytecode``
  3. return the last bytes in the diff ``creation_code-bytecode``

  Parameters:
  ===========
  :param explorer: the used explorer, e.g. etherscan
  :param address: the address of the contract
  :param on_chain_lookup: enables on-chain lookup instead of querying the explorer
  :param creation_tx_hash: optional hash of the tx when the contract was deployed.
                           Useful if the provided node can't determine the contract creation tx.
  :param bytecode: optional hex string of the compiled original source code
                   Useful if the explorer doesn't return valid constructor args or if they're incorrect.

  :return: a hex string with the constructor args used during deployment of the contract.
  """

  try:
      address = to_checksum_address(address)
  except ValueError:
      raise HTTPException(400, "invalid address")

  constructor_args = {
    "address": address,
  }

  rpc_url = None
  if "rpc_url" in config[explorer]:
      rpc_url = config[explorer]["rpc_url"]

  if on_chain_lookup:
      args = do_on_chain_lookup(explorer, rpc_url, address, creation_tx_hash, bytecode)
      constructor_args["constructor_args"] = args
      return constructor_args

  try:
      res = get_from_upstream(explorer, "contract", "getsourcecode", address)
  except ContractNotVerified:
      res = weak_cache(explorer, "contract", "getsourcecode", address)
  if res["message"] == "OK" and "result" in res:
      results = res["result"]
      if len(results) > 0:
          args = results[0]["ConstructorArguments"]

  if not args:
    # fallback if explorer api didn't return anything
    args = do_on_chain_lookup(explorer, rpc_url, address, creation_tx_hash, bytecode)

  constructor_args["constructor_args"] = args
  return constructor_args
