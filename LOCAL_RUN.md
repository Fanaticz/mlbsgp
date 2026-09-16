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
- `DK_COOKIE_BROWSER=1` (browser mint) is only useful on an egress Akamai
  already trusts; from a flagged IP the sensor never validates, whichever
  engine drives the browser. With `DK_PROXY` set the mint goes through the
  proxy too — see the next section.

## Residential / mobile proxy (`DK_PROXY`)

When the probe says `FAIL (403, cookie validated)`, the IP itself is scored and
the only fix is a different exit. A residential or mobile proxy gives a server
one without moving hosts. Three things have to be true for it to work:

1. **Sticky, not rotating.** Akamai binds the validated `_abck` to the IP that
   earned it, and the app spawns a fresh `dk_api.py` process per request — so
   with a rotating pool the cookie is minted on one exit and the pricing POST
   leaves from another, and nothing ever prices. Providers pin the exit
   through the proxy *username*. Write the provider's session token as
   `{session}` and the app fills in one id for every process on the host
   (kept in `DK_STATE_DIR`, re-drawn after `DK_PROXY_SESSION_TTL` seconds —
   default 600, inside every provider's sticky window — or pinned with
   `DK_PROXY_SESSION=<anything>`):

   | Provider | `DK_PROXY` (formats as of 2026-09 — check the provider docs) |
   |---|---|
   | Bright Data | `http://brd-customer-<ID>-zone-<ZONE>-session-{session}:<PASS>@brd.superproxy.io:33335` |
   | Oxylabs | `http://customer-<USER>-sessid-{session}-sesstime-10:<PASS>@pr.oxylabs.io:7777` |
   | Decodo (Smartproxy) | `http://user-<USER>-session-{session}-sessionduration-10:<PASS>@gate.decodo.com:7000` |
   | IPRoyal | `http://<USER>_session-{session}_lifetime-10m:<PASS>@geo.iproyal.com:12321` |

   Most providers also take a country/state selector in the same username
   (`-country-us-state-nj`, `-cc-US-st-us_new_jersey`, …). Use a **US** exit in
   a state DK serves — the pricing host is state-scoped (`DK_PRICE_HOST`,
   default NJ).
2. **Mobile > residential.** Akamai scores mobile-carrier ranges highest; if
   the provider offers a mobile pool, prefer it.
3. **The cookie must be minted on the same exit.** Either run the app on the
   proxy and paste a cookie from a browser that is *also* on it (rare), or
   set `DK_COOKIE_BROWSER=1` and let the app mint through the proxy itself —
   the mint reads `DK_PROXY` (with the same `{session}` id), so both hops
   present one IP. Minted cookies are cached in `DK_STATE_DIR` (owner-only
   file) for `DK_COOKIE_BROWSER_TTL` seconds and shared by every request's
   subprocess, so the browser runs once per TTL, not once per call.

### Browser mint engines (`DK_COOKIE_BROWSER_ENGINE`)

The mint needs a browser driver on the machine; none is in the deploy image
by default (all of this is inert unless `DK_COOKIE_BROWSER` is set).

| Engine | Install | Notes |
|---|---|---|
| `auto` (default) | — | `patchright` if installed, else `playwright`. |
| `patchright` | `pip install patchright && patchright install chromium` | Playwright fork with the CDP tells (`Runtime.enable`, the `__playwright` bindings) removed; same API. Preferred. |
| `playwright` | `pip install playwright && playwright install chromium` | Stock. Headless Chromium's `HeadlessChrome/…` UA is rewritten to `Chrome/…` (DK denies the former outright). |
| `uc` | `pip install seleniumbase` | SeleniumBase undetected-chromedriver mode. Downloads a matching chromedriver on first run. Works best **headed**: `DK_COOKIE_BROWSER_HEADLESS=0`, under `xvfb-run -a` on a server. |

Set `DK_CHROMIUM_PATH` if the browser binary isn't on the driver's default
search path. The mint loads the sportsbook, nudges the page (the Akamai sensor
posts after input events, not on a bare load), and if `_abck` still hasn't
validated halfway through `DK_COOKIE_BROWSER_WAIT` seconds (default 30) it
clicks through to `DK_COOKIE_BROWSER_PATH` (default the MLB league page) and
keeps polling.

What the engine **can't** do: validate from an exit Akamai already scores. From
a cloud container all three (patchright, playwright, UC headed under Xvfb) load
the page fine and `_abck` stays unvalidated — verified 2026-09-16. The engine
matters on a trusted exit; the exit matters everywhere.

### Testing a proxy, step by step

```bash
export DK_PROXY='http://…-session-{session}…:PASS@host:port'   # from the table
export DK_COOKIE_BROWSER=1 DK_COOKIE_BROWSER_ENGINE=patchright

# 1. mint only — no wager-endpoint call. Want: MINT OK, and the two IPs equal.
python3 scripts/probe_dk_price.py --mint-only

# 2. the real test — one calculateBets POST
python3 scripts/probe_dk_price.py
```

| `--mint-only` says | Meaning |
|---|---|
| `MINT OK` + browser ip == curl ip | The exit is trusted and sticky. Run step 2. |
| browser ip ≠ curl ip | The session isn't sticky — the `{session}` placeholder is missing or the provider ignores it. Fix `DK_PROXY` before anything else. |
| `MINT FAILED (_abck unvalidated)` | This exit is scored. Draw another (`DK_PROXY_SESSION=x2`), change location, or try a mobile pool. |

Note: this repo's cloud dev container only egresses on port 443, so
provider ports like 7777 / 7000 / 33335 can't be tested *from there* — run the
probe from Railway or a laptop.

Automated `calculateBets` calls are against DK's terms of service. The app
already prices sparingly (one POST per candidate combo, a breaker after 12
consecutive refusals); don't lower the breaker or loop the probe.

## Useful environment variables

| Variable | Purpose |
|---|---|
| `PYTHON` | Interpreter for the Python helpers. Auto-detected; override for Windows/venv setups. |
| `PORT` | HTTP port (default `3000`). |
| `DK_COOKIES` | DK cookie string. The in-app cookie box overrides this per call. |
| `DK_IMPERSONATE` | Pin the curl_cffi TLS profile list, e.g. `safari17_0`. Normally unnecessary — a profile the network resets is now retired automatically. |
| `DK_PRICE_BREAKER_403S` | Consecutive pricing 403s before pricing stops for the run (default `12`, `0` disables). |
| `DK_PROXY` | Route DK/Pinnacle traffic — and the browser mint — through a proxy, for a flagged host. `{session}` in the URL is replaced by one sticky id per host (see above). |
| `DK_PROXY_SESSION` | Pin the sticky id instead of drawing one (any string the provider accepts). |
| `DK_PROXY_SESSION_TTL` | Seconds before a drawn sticky id is replaced (default `600`). |
| `DK_STATE_DIR` | Where the sticky id and the minted-cookie cache live (default: `mlbsgp-dk` under the system temp dir; files are owner-only). |
| `DK_COOKIE_BROWSER` | `1` to mint a validated cookie with a browser (through `DK_PROXY` when set). |
| `DK_COOKIE_BROWSER_ENGINE` | `auto` / `patchright` / `playwright` / `uc` (see above). |
| `DK_COOKIE_BROWSER_HEADLESS` | `0` to run the mint browser headed (UC mode works best that way; use `xvfb-run` on a server). |
| `DK_COOKIE_BROWSER_WAIT` | Seconds the mint waits for `_abck` to validate (default `30`); it clicks through to `DK_COOKIE_BROWSER_PATH` halfway. |
| `DK_COOKIE_BROWSER_TTL` | Seconds a minted cookie is reused before re-minting (default `600`). |
| `DK_CHROMIUM_PATH` | Browser binary for the mint, if not on the driver's default path. |
| `DK_PRICE_HOST` | State-scoped pricing host (default `gaming-us-nj.draftkings.com`). |
| `SOCCER_LEAGUES_SWEEP` | Comma-separated league keys to narrow the sweep. |

## Security note

The app has **no authentication** on any route, and while a DK cookie is
loaded anyone who can reach the port can make DK calls with your session.
Bound to `0.0.0.0`, so it is reachable from your LAN. Keep it on a trusted
network, or use **CLEAR** in the cookie box when you're done. To reach it
remotely, front it with Tailscale or a Cloudflare Tunnel rather than
port-forwarding.
