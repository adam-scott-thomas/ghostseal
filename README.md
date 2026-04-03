# ghostseal

Lightweight audit client for Ghost_Logic Blackbox. Hash, batch, seal.

Every event gets a SHA-256 content hash, batched delivery to Blackbox, and automatic spill-to-disk when Blackbox is unreachable. Events are sealed into hash-chained GLCF capsules by Blackbox automatically.

## Install

```bash
pip install ghostseal
```

## Usage

```python
from ghostseal import SealClient

client = SealClient(
    blackbox_url="https://blackbox.ghostlogic.dev:8443",
    api_key="your-blackbox-api-key",
    source="myapp",
)

# Emit an audit event
client.emit("myapp.user.login", {"user_id": "abc", "ip": "1.2.3.4"})

# Events are batched and flushed automatically every 30s
# Or flush manually:
client.flush()

# On shutdown:
client.close()
```

## With spine

```python
from spine import Core
from ghostseal import SealClient

def setup(c):
    c.register("audit", SealClient(
        blackbox_url="https://blackbox:8443",
        api_key="...",
        source="ghostrouter",
    ))
    c.boot(env="prod")

Core.boot_once(setup)

# Anywhere in your code:
Core.instance().get("audit").emit("ghostrouter.call.complete", {
    "model": "claude-sonnet",
    "latency_ms": 1200,
    "cost": 0.003,
    "prompt_hash": "sha256:9f3...",
})
```

## How it works

```
your code → client.emit() → SealEnvelope (SHA-256 hashed)
                           → batch buffer (in memory)
                           → POST /api/v1/ingest (Blackbox)
                           → auto-sealed into GLCF capsule
                           → hash-chained, Merkle-verified, compressed

If Blackbox is down → spill to ~/.ghostseal/spill.jsonl
                    → client.drain_spill() when back up
```

## Part of the GhostLogic SDK

```
maelspine  → config registry
ghostseal  → audit backbone (this package)
ghostrouter → LLM routing
ghostserver → MCP tools
ghostprompt → prompt management (coming)
```

## License

Apache 2.0
