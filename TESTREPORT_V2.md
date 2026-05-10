# Kopis — Test Report V2 (post-recommendations)
**Date:** 2026-05-10  
**Engineer:** Claude (under Steven Johnston's direction)  
**Scope:** Re-test after implementing every recommendation from V1, plus identify (don't implement) further improvements found during this round.

---

## Headline result

After shipping the V1 recommendations:

| Metric | Original | V1 fixes | V2 fixes (now) |
|---|---|---|---|
| Findings from one shut-link cascade | 12 | 2 | 2 |
| Approvals/Jira tickets | 12 | 1 | 1 |
| Per-device Sonnet calls | 1 per finding device (up to 7) | 1 per finding device | **0 — single Sonnet per incident** |
| Topology agent calls on quiet snapshot | 18/18 | 18/18 (smart-skip not yet) | **4–18/18** depending on Ollama health |
| Cosmetic-only false positives | varies | 0 | **0** |

Per-device Sonnet was the largest residual waste; that's now eliminated.

---

## What shipped in this round

### 1. Per-incident Sonnet (token saving)

**Files:** `agents/state.py`, `agents/graph.py`, `services/correlation.py`, `api/routes/snapshots.py`, `api/routes/findings.py`

`run_pipeline()` gained a `defer_remediation` flag. Multi-device snapshot runs now stop the per-device pipeline at the topology stage. After all devices finish + correlation runs, `generate_incident_remediations()` makes ONE Sonnet call per incident — using the root-cause finding plus a brief summary of linked findings as context. Result: a 5-device cascade now costs 1 Sonnet call instead of 5.

Verified in TEST V1: every per-device pipeline shows `recs=0` and the model column shows only Haiku tokens. The single Sonnet call appears in the `incident_remediations_generated` log line at the end.

### 2. Frontend incident-grouped view

**Files:** `frontend/src/api/client.js`, `frontend/src/pages/Insights.jsx`

Insights page now defaults to an "Incidents" view that uses `/findings/incidents/list`. Each incident card shows the root cause plus an "INCIDENT · N findings · M devices" badge for correlated multi-finding incidents. Clicking expands to show linked findings inline. Users can toggle to a flat "All findings" view if they prefer.

### 3. Ollama 404 fixed

**File:** `.env`

Configured model `qwen2.5:14b` was not installed on the local Ollama; available models include `qwen2.5:7b`. Switched the env var. Verified Ollama now responds to `/api/generate` with valid output.

### 4. Topology-aware correlation (entity overlap + topology overlay)

**File:** `services/correlation.py`

Added `_load_topology_neighbors()` which builds a device-to-device adjacency map from the topology service's BGP edges and L2 segments. `_correlate_with_topology()` runs the standard entity-based grouping first, then merges any incidents whose findings sit on directly-connected devices AND share a category family. Catches the case where two ends of a broken link don't textually share an entity.

### 5. Aggressive Ollama timeout + fallback awareness

**Files:** `integrations/ollama.py`, `agents/nodes/normaliser.py`, `agents/nodes/topology.py`

- Ollama HTTP timeout cut from 120s to 30s. Tier 0 should be fast; if the local model is slow, the deterministic fallback is far better than blocking the whole snapshot pipeline.
- The fallback now stamps `_used_fallback: True` on the normalised data.
- The topology agent's smart-skip now requires that the FULL Ollama normaliser ran (not the fallback). Empty anomalies from the fallback are not a reliable "no work needed" signal — the fallback is less thorough than Ollama.

This was a correctness fix discovered mid-test: smart-skip was firing on every device when Ollama timed out, causing real findings to be missed.

---

## TEST V1 — cascade with all fixes

**Scenario:** `shutdown` Ethernet0/0 on S1-R1 (eBGP uplink to DC1-R1), wait 200s for BGP holdtime, snapshot all 18 devices.

**Results:**
- Snapshots: 18/18 ok, 0 failed
- Pipelines: 18/18 complete
- Topology agent calls: 18 (no smart-skip — Ollama-fallback was used because Ollama timed out on most devices in the test environment)
- Findings created: 2
- **Incidents: 2** (1 multi-device correlated, 1 solo)
  - **Incident A (correlated)**: "BGP neighbor 192.168.1.1 stuck in Idle state" on S1-R1 + "BGP neighbor 192.168.1.2 in Idle state" on DC1-R1 → ONE incident
  - **Incident B (solo)**: "Interface Ethernet0/0 admin-down with configured IP address" on S1-R1
- **Approvals: 1** (PSR-85, on the BGP cascade — the interface finding had `requires_remediation=False`)
- Per-device Sonnet calls: 0 (deferred)
- Per-incident Sonnet calls: 1
- Total tokens: ~148K Haiku + ~8K Sonnet

**Verdict:** ✅ Cascade collapsed correctly. Per-incident Sonnet eliminated per-device token waste.

---

## TEST V3 — cosmetic-only change

**Scenario:** Update interface description on S1-R2 (twice — first as new baseline, second to create a description-only diff). Snapshot all 18 devices.

**Results (phase 2):**
- Snapshots: 18/18 ok
- Pipelines: 18/18 complete
- **Topology agent skipped: 4/18** (devices where Ollama responded successfully and saw no anomalies; smart-skip activated)
- **Findings created: 0**
- Approvals: 0

**Verdict:** ✅ Cosmetic-only change correctly produced no false positives. Smart-skip did fire on the devices where the full Ollama normaliser returned cleanly.

---

## Improvement opportunities discovered during V2 testing (NOT implemented)

These came out of running the variation tests. Each is genuinely worth doing — listing them in priority order so the next session can pick the highest-value items.

### P0 — Same-device cross-category correlation

The interface finding ("Eth0/0 admin-down") and the BGP findings ("BGP neighbor 192.168.1.1 stuck in Idle state") are obviously the same incident — interface failure causes BGP failure on the same device. But the current correlation:
1. Doesn't merge by entity overlap (interface finding mentions "Ethernet0/0", BGP finding mentions IP "192.168.1.1" — no shared text)
2. Doesn't merge by topology either (topology-merge only fires for *different* devices)

The interface finding and the BGP findings on the same device should always merge. Add a third correlation pass: any two findings on the same device whose categories are causally related (interface → routing, routing → routing) get merged, with the lower layer (interface) as root.

**Impact:** Test V1 would produce 1 incident (root: interface admin-down) instead of 2.

### P0 — Slow Ollama is the dominant pipeline cost

With Ollama timing out at 30s on most devices, every snapshot run loses ~9 minutes (18 × 30s) waiting for fallback to kick in. Before the timeout fix it was much worse (120s × 18 = 36 min). 

Options:
- Make Ollama optional via config flag — skip it entirely when known unreliable, save the 30s wait
- Cut the prompt size sent to Ollama (currently 60K chars truncated). qwen2.5:7b on remote hardware can't process that fast. Pre-extract the structural fields and send a 2–5K compact summary
- Add a circuit breaker: after N consecutive Ollama timeouts, skip Ollama for the rest of the snapshot run

The current behaviour wastes wall-clock time even when smart-skip would otherwise fire.

### P1 — Correlation across snapshot generations (history-aware)

Each snapshot run only correlates the findings produced in that run. If a problem persists across snapshots (the cascade is still ongoing N hours later), the new run's findings get deduped to the OLD ones (good), but they're correlated with each other from scratch, ignoring the prior incident_id. Result: the same incident may get a NEW incident_id on every snapshot.

Fix: when a finding is deduped to an existing one, inherit that finding's `incident_id` instead of getting a fresh one in the new correlation pass.

### P1 — Surface the AI's reasoning per-finding more clearly

The Sonnet recommendation includes excellent reasoning ("BGP neighbor 192.168.1.1 is in Idle state because the interface Ethernet0/0... bringing this up will inject routes... risk is medium because..."). But the Insights UI currently buries it inside the finding-detail modal. Pull it onto the incident card itself — that's the most valuable part of the AI output and right now it's two clicks deep.

### P1 — `requires_remediation=False` on the actual root cause is wrong

In TEST V1 the interface finding ("Eth0/0 admin-down with configured IP address") was correctly identified by Haiku, but marked `requires_remediation=False`. So no Sonnet was called for it, no approval was created — yet it's the actual root cause that needs fixing.

The system happens to work in this test because Sonnet (called on the BGP finding) correctly figured out the underlying fix is `no shutdown Eth0/0` — but only because the BGP-to-interface link was implicit in the data. In other failure modes, suppressing remediation on a clear "this is broken on purpose" finding would be wrong.

The Haiku prompt's rule "Interfaces that are admin-down (intentionally disabled — this is expected)" is too absolute. Refinement: if admin-down is observed AND the diff shows it WAS up before, it's a state change that may need remediation.

### P2 — DC2-R2 has a real persistent issue

Across every test run, DC2-R2 reports "BGP established with zero routes received" / "BGP established but zero routes advertised". This is real, not a false positive. Worth investigating outside of test scope — likely a route-map, prefix-list, or peer-group misconfiguration.

### P2 — Pre-execution sanity check

When approving a remediation, run a quick "is this still relevant?" check before executing — re-fetch the device's current state, confirm the symptom still exists, and only then run the commands. In TEST 4 the interface was shut for 5+ minutes by the time approval ran; in production a human approver might take hours. The world may have changed.

### P2 — Snapshot scheduler + correlation race

The hourly snapshot scheduler doesn't currently coordinate with manual snapshots. If a manual snapshot is mid-correlation when the scheduler fires, the second run gets `409 Conflict`. Acceptable today but worth a "queue next run" semantic so scheduled runs aren't silently dropped.

### P3 — Correlation reason quality

Linked findings show "Linked to root cause: 'X' on the same incident." A more useful summary would be the AI's actual reasoning about why they're linked. Could ask Sonnet (in the per-incident remediation call) to also produce a "why these are linked" sentence.

### P3 — Vector dedup threshold tuning

Some "different but related" findings (e.g. "BGP routes withdrawn" on Device A vs "BGP routes withdrawn" on Device B with different prefix sets) may dedupe each other when they shouldn't. Worth quantifying the dedup threshold and adding a per-device guard so we don't dedupe ACROSS devices.

### P3 — UI: Incident-only badge confusion

The INCIDENT badge currently shows on multi-finding incidents only. Solo "incidents" (1 finding) look identical to a regular finding. Consider always showing the badge OR rebrand the page entirely as "Incidents" with a finding count.

---

## Files changed this round

- `.env` (Ollama model)
- `backend/agents/state.py` (added `defer_remediation`)
- `backend/agents/graph.py` (deferral routing + `defer_remediation` parameter)
- `backend/agents/nodes/normaliser.py` (set `_used_fallback` flag)
- `backend/agents/nodes/topology.py` (smart-skip respects fallback flag)
- `backend/integrations/ollama.py` (30s timeout)
- `backend/services/correlation.py` (`generate_incident_remediations`, `_load_topology_neighbors`, `_correlate_with_topology`)
- `backend/api/routes/snapshots.py` (calls `generate_incident_remediations` between correlation and approvals)
- `backend/api/routes/findings.py` (recorrelate endpoint also runs incident remediations)
- `frontend/src/api/client.js` (incidents endpoints)
- `frontend/src/pages/Insights.jsx` (IncidentCard component, view-mode toggle, incidents-first default)

---

## Recommendation

The v2 implementation is a meaningful improvement on top of v1. Per-incident Sonnet eliminates the largest remaining token waste. Topology-aware correlation closes a known gap. The Ollama timeout fix is necessary to prevent 30+ minute pipeline runs.

The single most valuable next step is **same-device cross-category correlation** (P0 above) — it would have collapsed TEST V1 to 1 incident instead of 2. The fix is small (~30 lines) and well-scoped.
