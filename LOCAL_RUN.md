# Running it on your own machine

The soccer tab works better from a home connection than from a deployed
server, and needs no local data files — it fetches Pinnacle and DK live on
each scrape. (The multi-GB `.xlsx` / `public/data/*.json` files are only for
the MLB and NBA tabs.)

## Why local beats a deployed host for DK

Two separate DK obstacles, and running locally sidesteps both:

1. **IP reputation.** DK's Akamai edge scores datacenter IPs and 403s the
   pricing endpoint (`calculateBets`) from them — a validated cookie does not
   help. A home broadband IP is an ordinary residential IP and isn't carrying
   that penalty.
2. **Cookie/IP mismatch.** An Akamai `_abck` cookie is bound to the IP that
   earned it. Pasting a cookie minted in your browser at home into a server in
   another state presents that cookie from an IP it was never issued to, which
   is a signal Akamai looks for. Run the app on the same machine as the browser
   you copy the cookie from and they match.

## Setup

```bash
git clone https://github.com/Fanaticz/mlbsgp.git
cd mlbsgp
npm install
pip install -r requirements.txt      # curl_cffi (TLS impersonation) + openpyxl
npm start                            # → http://localhost:3000
```

Requires **Node ≥18** and **Python 3**. On boot the server logs which
interpreter it resolved:

```
Python interpreter: python3 (override with PYTHON=...)
Listening on 0.0.0.0:3000
```

### Platform notes

- **Windows** — the launcher is normally `python`, not `python3`, and a bare
  `python3` may hit the Microsoft Store stub (which surfaced as an opaque
  `exited with code 9009`). The interpreter is now auto-detected, so this
  should just work; if it doesn't, set it explicitly:
  `set PYTHON=py` (cmd) or `$env:PYTHON="py"` (PowerShell).
- **macOS with Homebrew Python** — if `pip` maps to a different Python than
  `python3`, install with `python3 -m pip install -r requirements.txt` so
  `curl_cffi` lands in the interpreter the server actually spawns.
- **Linux (Debian/Ubuntu)** — an externally-managed Python needs either a venv
  or `pip install --break-system-packages -r requirements.txt`.

## Using the soccer tab

1. Open <http://localhost:3000> → **Soccer** tab.
2. On **draftkings.com**, click into a game and add 2 legs to the bet slip
   (this is what makes Akamai validate the cookie — a plain page load leaves
   `_abck` unvalidated and pricing will 403). Then in DevTools → Console run
   `copy(document.cookie)`.
3. Expand **🔑 DK cookie (real SGP pricing)**, paste, **Save**. The summary
   must read `validated`; if it says `unvalidated`, interact with the game page
   a little more and copy again.
4. Click **✨ SCRAPE SGPS**.

The status line above the table tells you where you stand:

| Status | Meaning |
|---|---|
| 🟢 DK SGP pricing live — priced N combo(s) | Working. `DK SGP` / `EV%` / `Kelly` columns are populated. |
| 🟠 …priced N, then DK started refusing | Partial: your IP is rate-limited. Some prices are real; the rest went unpriced. |
| 🟠 DK blocked this server's IP despite a validated cookie | IP is flagged. Only `DK_PROXY` (residential) fixes this. |
| 🔴 DK unreachable (`_abck` unvalidated/absent) | Cookie problem — redo step 2. |

Cookies last a few hours and are held **in server memory only**, so re-paste
after a restart.

## Testing whether a VPN / proxy can price DK SGPs

`scripts/probe_dk_price.py` runs one real 2-leg pitcher SGP through
`calculateBets` on whatever egress you give it and prints a verdict that
separates the two things Akamai 403s on — the IP and the `_abck` cookie —
so a VPN trial gets a yes/no instead of another "Access Denied".

```bash
# 1. connect the VPN (or export DK_PROXY=http://user:pass@host:port)
# 2. baseline — expect "AMBIGUOUS" here: no validated cookie yet
python3 scripts/probe_dk_price.py
# 3. mint a validated cookie ON THE SAME EGRESS: open draftkings.com in a
#    normal browser, open a game, add 2 legs to the bet slip, then in the
#    DevTools console run copy(document.cookie)
# 4. the real test
DK_COOKIES='<paste>' python3 scripts/probe_dk_price.py
```

| Verdict | Meaning |
|---|---|
| `PASS — DK priced the SGP at …` | This egress + cookie can drive the +EV finder. Run the app from here. |
| `FAIL (403, cookie validated)` | The cookie is fine; Akamai has scored the IP itself. Only a different exit (another VPN server, a residential proxy) changes this. |
| `FAIL (403, _abck unvalidated)` | Not a verdict on the IP yet — redo step 3 (interact with a game page more, copy again). |

Notes:
- The browser that mints the cookie and the script must share the egress.
  Akamai binds `_abck` to the IP that earned it, so a cookie copied from a
  home browser will not rescue a server in another location, and vice versa.
- Pass a pitcher name to pick the game: `python3 scripts/probe_dk_price.py Yamamoto`.
- Read endpoints (`games`, `markets`) work from datacenter IPs; only the
  pricing POST is IP-scored. A datacenter host that fails the probe with a
  validated cookie (observed 2026-09-15 from a cloud container: markets fine,
  homepage 200 via curl_cffi, headless Chromium denied outright, pricing 403)
  needs a residential `DK_PROXY` — there is no cookie-side fix.
- `DK_COOKIE_BROWSER=1` (headless Chromium mint) is only useful on an egress
  Akamai already trusts; from a flagged IP the sensor never validates.

## Useful environment variables

| Variable | Purpose |
|---|---|
| `PYTHON` | Interpreter for the Python helpers. Auto-detected; override for Windows/venv setups. |
| `PORT` | HTTP port (default `3000`). |
| `DK_COOKIES` | DK cookie string. The in-app cookie box overrides this per call. |
| `DK_IMPERSONATE` | Pin the curl_cffi TLS profile list, e.g. `safari17_0`. Normally unnecessary — a profile the network resets is now retired automatically. |
| `DK_PRICE_BREAKER_403S` | Consecutive pricing 403s before pricing stops for the run (default `12`, `0` disables). |
| `DK_PROXY` | Route DK/Pinnacle traffic through a proxy, for a flagged host. |
| `DK_PRICE_HOST` | State-scoped pricing host (default `gaming-us-nj.draftkings.com`). |
| `SOCCER_LEAGUES_SWEEP` | Comma-separated league keys to narrow the sweep. |

## Security note

The app has **no authentication** on any route, and while a DK cookie is
loaded anyone who can reach the port can make DK calls with your session.
Bound to `0.0.0.0`, so it is reachable from your LAN. Keep it on a trusted
network, or use **CLEAR** in the cookie box when you're done. To reach it
remotely, front it with Tailscale or a Cloudflare Tunnel rather than
port-forwarding.
