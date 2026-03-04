# Container Network Limitation — Cause & Fix Options

## Context

This project uses a containerized Claude Code development environment. The container has outbound internet access, but it is **not direct** — all traffic is routed through an HTTP/HTTPS proxy at `host.docker.internal:3128`.

---

## What Works

- `curl` and browser-based tools reach the internet fine (proxy is transparent to curl)
- DuckDuckGo search via MCP tools works
- `googleapis.com` is reachable via curl (returns real API responses)

## What Fails

- Python libraries that make HTTP calls directly using their own socket connections — specifically **`httplib2`** (used by `google-api-python-client`) — get `ConnectionRefusedError` instead of routing through the proxy

---

## Root Cause

The container network is configured with:
- `https_proxy=http://host.docker.internal:3128` (set in environment)
- A firewall that **blocks direct outbound connections** on port 443

Tools like `curl` automatically respect `https_proxy` and tunnel through the proxy.

However, **`httplib2`** has inconsistent proxy support:
- It reads `https_proxy` from the environment in some versions
- But in practice it often tries a direct TCP connection first, which gets refused by the firewall
- The result: `ConnectionRefusedError: [Errno 111] Connection refused`

This is **not** a "no internet" problem — the proxy allows the traffic. It's a **library-level proxy compatibility** issue.

---

## Solutions

### Option 1: Switch transport to `requests` + `httpx` (Recommended)

Replace `httplib2` with a `requests`-based HTTP transport for `google-api-python-client`:

```python
import google.auth.transport.requests
from googleapiclient.discovery import build

# requests respects https_proxy env var reliably
authed_session = google.auth.transport.requests.AuthorizedSession(creds)
service = build("gmail", "v1", credentials=creds, requestBuilder=None)
```

Or use the `google-auth-requests` transport explicitly.

### Option 2: Patch httplib2 proxy at runtime

```python
import httplib2
import os

proxy_url = os.environ.get("https_proxy", "")
# parse proxy host/port and pass to httplib2.Http(proxy_info=...)
proxy = httplib2.ProxyInfo(
    proxy_type=httplib2.socks.PROXY_TYPE_HTTP,
    proxy_host="host.docker.internal",
    proxy_port=3128,
)
http = httplib2.Http(proxy_info=proxy)
```

Pass this `http` object when building the Google API service.

### Option 3: Request firewall allowlist for googleapis.com

Ask the container environment admin (or the Claude containerized dev setup project) to allowlist direct connections to:
- `googleapis.com:443`
- `oauth2.googleapis.com:443`
- `accounts.google.com:443`

This removes the need for any library-level proxy fix.

### Option 4: Run API-calling code on host Mac, not in container

Keep the container for code editing and logic, but run `python3 test_gmail.py` locally on the Mac where there's no proxy restriction.

---

## Questions to Ask the Containerized Claude Dev Setup

> Our Claude Code container routes all outbound traffic through a proxy at `host.docker.internal:3128`. `curl` works fine, but Python's `httplib2` library gets `ConnectionRefusedError` because it doesn't reliably use the proxy env vars.
>
> Options we see:
> 1. Allowlist direct connections to `googleapis.com:443` at the firewall level
> 2. Configure the proxy to be transparent so all TCP connections are automatically proxied (TPROXY)
> 3. Inject proxy settings into the container's Python environment at a lower level
>
> What's the recommended approach for this setup?

---

## Current Workaround

Run `python3 test_gmail.py` on the host Mac (not inside the container). The Gmail connector code is correct — it just can't be tested from within the container until one of the above fixes is applied.
