# Pass 1 health flap (11:47:54 IST, 2026-10-15) — read-only investigation findings

Sources (all existing, local, read-only; no network, no GX10 contact): `cf56cdd` source; the Stage A store
(SQLite, mode=ro) → `decision-timeline.tsv`, `decisions-around-flap.2.json`; macOS unified log and `pmset -g log` →
`pmset-log.txt`, `pmset-sleepwake.2.txt`, `log-powerd-sleep.2.txt`, `log-tailscale.txt`, `log-network.txt`,
`log-power.txt`. Report/checkpoint hashes unchanged (d72ddc66… / 6d1ca65c…).

## What the code establishes
- The exclusion string `backend unhealthy: ollama: ConnectTimeout: ` is produced only by `BaseAdapter._get_json`
  (`f"{cfg.id}: {ExceptionClass}: {e}"`, httpx's ConnectTimeout has an empty message) — i.e. a GET on the Ollama
  native API, not an inference call. `healthy = False` is set in exactly two places, both in the gateway's
  background loop (`_background`, tick every `residency_refresh_s` = 15 s): `refresh_residency()` →
  `health()` → GET `/api/version`; or the 120 s full `refresh()` → `discover()` → GET `/api/tags` (+ health).
  The inference path never sets `healthy = False`. Connect timeout 5 s (`connect_timeout_s`).
- httpx's pooled keep-alive connections expire after 5 s idle, so every 15 s poll opens a NEW TCP connection to
  `100.83.54.124:11434`; the in-flight inference request keeps its own connection.
- Decision `created_at` = wall-clock routing time; the store's `created_at` column = save time at completion.
- `latency_ms` in the checkpoint and `outcome_detail` elapsed are `time.monotonic()` differences; on macOS CPython
  uses `mach_absolute_time`, which does not advance while the Mac sleeps.

## What the logs establish (wall clock, IST)
| time | event | source |
|---|---|---|
| 11:44:02.217 | test gemma4 `ambig-02` routed; completed 11:44:34.053 (31.8 s) | store |
| 11:44:34.056 | test gemma4 `ambig-03` routed and dispatched to the GX10 | store |
| 11:44:32 | display off; `kIOMessageCanSystemSleep` | powerd |
| **11:44:55** | **"Entering Sleep state due to 'Idle Sleep'"** (TCPKeepAlive=active, on AC) | pmset |
| **11:47:34** | **"Wake from Deep Idle … pwrbtn … UserActivity"; clamshell opened; Wi-Fi re-associated and `utun4` (Tailscale) registered within ~1 s** | pmset, airportd, mDNSResponder |
| 11:47:34–11:47:54 | the gateway's background loop resumed; one GET on a new TCP connection timed out after 5 s → all four deployments `healthy=False` | code + records |
| 11:47:54.572 | `ambig-03` completed, outcome ok, upstream elapsed 43573 ms monotonic (≈ 21 s before sleep + ≈ 20 s after wake) | store |
| 11:47:54.575–.683 | 103 requests refused in 108 ms (`no_eligible`) | store |
| ≈11:47:55 | launcher's own `curl /api/ps` to the GX10 succeeded | 50-pass1.txt |

So: **the Mac went to idle sleep for 159 s in the middle of Pass 1** (no process held a sleep assertion; the
launcher did not use `caffeinate`), and the ConnectTimeout occurred within the first 20 s after wake. The
pre-sleep inference connection survived and delivered its response at 11:47:54; the health poll's new
connection in that window did not complete a TCP handshake within 5 s. The run's 157 s "gap" between
ambig-02 and ambig-03 is the sleep; the harness's monotonic latencies hide it.

## What remains unknown
- Why that specific post-wake connect did not complete within 5 s. Hypotheses, none verified: the Tailscale
  WireGuard path to the GX10 was not yet re-established after wake (the Tailscale network-extension daemon
  log was not found in the unified log; its own log files were not located); a transient Wi-Fi/AP condition
  after re-association; the GX10 side. The GX10 logs were not read (no GX10 contact permitted).
- Whether Ollama had finished generating `ambig-03` long before 11:47:54 (the response then simply waited
  for the Mac) — the GX10 Ollama log would show this.

## Smallest useful next diagnostics (read-only)
1. Owner-run on the GX10: Ollama server log and `modelsaar.service` journal for 11:44:30–11:48:00 IST
   (ambig-03 accept/complete times; any connection errors; whether production's own health polls saw anything).
2. On the Mac: Tailscale's daemon log for 11:47:34–11:47:55 via the Tailscale app's log export (local), to see
   when the peer path to the GX10 was re-established after wake.
3. Nothing else is needed to explain the flap's trigger; the sleep is established.

---

## Update 2026-10-15 19:30 IST — Mac Tailscale daemon log and owner-provided GX10 logs

New sources: Mac unified log, process `IPNExtension` (Tailscale network extension) → `log-tailscale-ext.3.txt`
(`64_tailscale_logs_readonly.command`; the Tailscale app containers themselves are TCC-protected and were not read);
GX10 journal extract supplied by the owner (`gx10-journal-2026-10-15-0614-0618utc.txt`: `ollama`, user
`modelsaar.service`, `tailscaled`, 06:14:30–06:18:00 UTC). GX10 clock is Asia/Singapore (+08) = IST + 2 h 30 m;
times below are IST unless marked. Benchmark and decision evidence unchanged.

### Matching the GX10 inference lines to Pass 1 records
| GX10 (Ollama, +08 → IST) | Mac store / checkpoint | match |
|---|---|---|
| task 5222: total 31273 ms; `POST /v1/chat/completions` 200, 31.348 s, from 100.106.107.13, logged 14:14:33 (= 11:44:33) | `ambig-02` routed 11:44:02.217, upstream 31836 ms, saved 11:44:34.053 | timing and source agree to the second |
| task 5539: new prompt 18 tokens at 14:14:34 (= 11:44:34); 400 tokens generated (= the `max_tokens` cap); total 36496 ms; `POST /v1/chat/completions` 200, 36.555 s, from 100.106.107.13, logged **14:15:10 (= 11:45:10)** | `ambig-03` routed **11:44:34.056**, upstream 43573 ms (monotonic, excludes sleep), saved **11:47:54.572** | start time and source agree to the second; it is the only Mac inference request in the window |

Ollama does not log the gateway's request id, so the association cannot be confirmed by identifier.
**Label: likely (strong timing/source match), unconfirmed by id.**

### What the GX10 logs establish
- **Server-side inference completed at 11:45:10 IST**, 15 s after the Mac entered sleep (11:44:55) and 2 m 44 s
  before the Mac recorded the response (11:47:54.572). Ollama's 36.5 s plus the Mac's ≈21 s awake before sleep and
  ≈20 s after wake are consistent with the Mac's 43.6 s monotonic figure. Correlation strength: strong on timing,
  source address and the sequence of the two requests; not an identifier match. Whether the response bytes
  were acknowledged before the sleep or retransmitted after wake is not recorded on either side.
- The Mac's health polls reached Ollama at 11:44:32/33 and **11:44:48** (last before sleep, both 200). **No request
  from 100.106.107.13 is logged between 11:44:48 and 11:47:55.** The Mac's failed `/api/version` connect
  (≈11:47:40.6–45.6, per the Mac's `open-conn-track` line) therefore never reached Ollama — expected, since a TCP
  connect that times out before the handshake produces no server-side request log line. The GX10 logs do not
  directly record that failure.
- **Route recovery, GX10 side (`tailscaled`, peer `[qYvoe]` = the Mac):** 11:47:34 and 11:47:39 "derp-6 does not
  know about peer, removing route"; 11:47:42 and 11:47:43 "new contact via=derp"; 11:47:48 "removing route" again;
  11:47:49 and **11:47:54 "new contact via=derp"**. The Mac side shows derp-3 reset/reconnect 11:47:38, derp-6
  reset/reconnect 11:47:50, and the GX10's disco key update at 11:47:54.48; the pending response arrived 11:47:54.572.
- **Connectivity by 11:47:55 IST is established:** Ollama logged `GET /api/ps` 200 from 100.106.107.13 at
  14:17:55 (+08) = 11:47:55 IST — the launcher's post-run snapshot.
- GX10 local health: the production `modelsaar.service` polled `127.0.0.1:11434` every 15 s with 200s throughout
  (including 14:17:30 and 14:17:45 +08), and Ollama answered a LAN client (192.168.0.10) at 14:17:46. This shows
  the GX10's services were healthy; it says nothing about whether the Mac's remote poll reached the GX10.

### What this narrows (findings)
The failed connect fell inside a window (11:47:34–11:47:54) in which **both ends** logged the Tailscale relay path
between them being torn down and re-established repeatedly: the Mac's DERP connections were reset after wake, and
the GX10's `tailscaled` removed and re-added the route to the Mac at 11:47:34, :39, :48 with contacts at :42, :43,
:49, :54. Ollama and the GX10 services were up and serving other clients throughout; the Mac's poll never reached
them. The timeout was a path failure during post-wake Tailscale re-establishment, not a server failure.

### Inference (not logged as such)
The specific SYN (Mac :56097 → GX10 :11434, ≈11:47:40.6) was most plausibly dropped on a relay connection that one
side still considered live (the Mac reconnected derp-6 only at 11:47:50; the GX10 had removed the route at 11:47:39
and re-added it at 11:47:42/43). Which hop discarded it, and why the GX10's route to the Mac flapped three times
rather than once, is not recorded anywhere.

### Still unknown
Which relay/hop dropped the SYN; whether Ollama's response was acknowledged before sleep or retransmitted after
wake; whether a direct (non-DERP) path would have behaved differently (the Mac's disco pings to the GX10's LAN
endpoint 192.168.0.12:41641 failed "no route to host"/"host is down" — the two hosts are on different networks).
