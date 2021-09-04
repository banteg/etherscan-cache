# etherscan-cache

A simple caching server for Etherscan-like APIs.

## Installation

Install dependencies
```
pip install -r requirements.txt
```

Create a `config.toml`, specify upstreams with their corresponding API keys.
```
[etherscan]
url = "https://api.etherscan.io/api"
keys = [
    "V53X2WJ37502KMJFXOZB30V0JHNMO11IEO",
    "C6CS0ELHNKQJOL5KUGJVI9UOX3PRECYOZW",
    "4Q465Q32P2C7E7M0COZYSOM22GCHHW2T4G",
    "0NWN4412GB0X9KNH7XH4220UMB6F28CIIH",
    "UO6F66X8H2NS0ALAJNQIXQP6APO74O0UAU",
]
```

The keys will be used in a round robin manner. All requested sources and ABIs will be forever cached.

Run with uvicorn.
```
uvicorn app:app --port 8000
```

Front with something like Caddy if you need `https`.

## API

- `/{explorer}/api` forwards to upstream api
- `/stats` cache stats (hits, misses, count, size)
