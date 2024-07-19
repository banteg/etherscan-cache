import requests
import json
from fastapi import HTTPException

def get_creation_tx(address: str, url: str) -> str:
  res = requests.post(
    url,
    json= {
      "jsonrpc": "2.0",
      "id": 1,
      "method": "ots_getContractCreator",
      "params": [address]
    }
  )
  if res.status_code != 200:
    return None

  results = res.json()
  return results["result"]["hash"]

def get_creation_code(tx: str, url: str) -> str:
  res = requests.post(
    url,
    json= {
      "jsonrpc": "2.0",
      "id": 1,
      "method": "eth_getTransactionByHash",
      "params": [tx]
    }
  )
  if res.status_code != 200:
    return None

  results = res.json()
  return results["result"]["input"]

def do_on_chain_lookup(explorer: str, rpc_url: str, address: str, creation_tx_hash: str, bytecode: str) -> str:
    if not rpc_url:
          raise HTTPException(404, f"no rpc configured for explorer {explorer}")

    if not bytecode:
        raise HTTPException(400, f"no bytecode provided for address {address}")

    if not creation_tx_hash and rpc_url:
        # this only works for nodes which can determine the creation tx
        creation_tx_hash = get_creation_tx(address, rpc_url)

    if not creation_tx_hash:
        raise HTTPException(404, f"creation tx not found for address {address}")

    creation_code = get_creation_code(creation_tx_hash, rpc_url)
    if not creation_code:
        raise HTTPException(404, f"creation code not found for tx {creation_tx_hash}")

    # The constructor args are appended at the end of the creation_code.
    # Substracting the length of the original compiled bytecode will return
    # the length of the constructor args which we can then use as offset for
    # slicing the creation_code.
    length = len(creation_code) - len(bytecode)

    args = ""
    if length > 0:
        # return the last "length" bytes from the creation_code
        args = creation_code[-length:]

    return args
