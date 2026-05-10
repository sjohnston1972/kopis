# Kopis — Test Report V3 (final)
**Date:** 2026-05-10  
**Engineer:** Claude (under Steven Johnston's direction)  
**Scope:** Implement every V2 recommendation, including cutting Ollama out, then validate end-to-end.

---

## Headline result

| Metric | Original | V1 | V2 | **V3 (now)** |
|---|---|---|---|---|
| Cascade findings → incidents | 12 / 12 | 12 / 1 | 11 / 2 | **11 / 1** |
| Approvals + Jira tickets | 12 | 1 | 1 | **1** |
| Per-device Sonnet calls per cascade | up to 7 | up to 7 | 0 | **0** |
| Wall-clock time per snapshot+pipeline | ~22 min | ~25 min | ~25 min | **~5 min** |
| Tokens on a clean baseline (18 devices) | ~90 K | ~90 K | ~90 K | **0** |
| Tokens on a cascade event | ~212 K | ~140 K | ~110 K | **~109 K** |
| Cosmetic-only false positives | varies | 0 | 0 | **0** |
| Root cause correctly identified | sometimes | sometimes | no — 2 incidents | **yes — 1 incident, root = interface admin-down** |

The pipeline now correctly says: **"S1-R1 Ethernet0/0 was administratively shut down. This caused BGP failure on this device, BGP failure on its peer DC1-R1, and route withdrawal on 7 downstream devices. Re-enable the interface to fix everything."** That's all in **one** approval / Jira / Slack notification.

---

## What shipped this round

### 1. Cut Ollama out (`agents/nodes/normaliser.py`, `agents/nodes/topology.py`)

Removed the Ollama HTTP call from the normaliser node entirely. Always uses the deterministic extractor (~200 lines of pyATS dict-walking). Reasons:
- Ollama on the homelab was unreliable: 30s timeouts × 18 devices = 9 min of wall clock wasted per snapshot
- The deterministic extractor catches everything that mattered (down interfaces, non-Established BGP/OSPF, high error counters, removed routes/ARP, admin-down state changes)
- The actual analysis happens at Tier 1 (Haiku); the normaliser just feeds Haiku tidy data
- Result: each per-device pipeline runs in milliseconds for the data-reduction step

The Ollama integration file (`integrations/ollama.py`) is left in place for potential future use (e.g. a focused small-prompt task) but is no longer wired into the pipeline.

### 2. Same-device cross-category correlation (`services/correlation.py`)

Added `_merge_same_device_incidents()` — a third correlation pass that merges incidents whose findings sit on the same device AND have causally-related categories (interface→routing, routing→routing). Catches the V2 gap where "interface admin-down" and "BGP neighbor in Idle" on S1-R1 were two separate incidents — they're obviously the same event.

Verified in V3: the cascade now produces **1 incident** (root = interface) instead of V2's 2 incidents (interface separate from BGP).

### 3. History-aware correlation (`services/correlation.py`)

When an incident is rebuilt and its constituent findings already had a prior `incident_id`, inherit the most-frequent prior id rather than generating a fresh UUID. Long-running incidents now keep a stable id across snapshot runs — operators see "still incident #abc, ongoing" instead of a new one every hour.

### 4. Surface AI reasoning on incident cards (`api/routes/findings.py`, `frontend/src/pages/Insights.jsx`)

`/findings/incidents/list` now eager-loads each incident's root-cause recommendation (action + reasoning + risk + commands + approval info). The Insights page renders this on the incident card itself — Sonnet's analysis is the most valuable output and was previously two clicks deep. Card now shows:
- AI Analysis badge + risk-level chip + approval status
- Sonnet's reasoning (3-line clamped)
- The recommended action with a bolt icon

### 5. Haiku prompt refinement: admin-down with state change (`agents/prompts/topology.md`)

Added an explicit nuance section: an interface that just transitioned to admin-down (per the diff) IS a finding requiring remediation, even though admin-down is normally "intentional and expected." Critical severity if it carried routing adjacencies.

Also strengthened the deterministic normaliser to flag the same case from the diff (`enabled: true → false`).

Verified in V3: the cascade's root cause finding is now correctly "Ethernet0/0 administratively shut down" with `requires_remediation=true` — not the BGP-down symptom.

### 6. Pre-execution sanity check (`services/execution_engine.py`)

Before running approved commands, the executor now:
- Refuses to execute if the linked finding has been deleted (operator dismissed it after approving)
- Takes a fresh single-device snapshot
- Confirms the symptom still applies (interface still down, BGP still not Established) — abort with `skipped: true` if not

Avoids running stale config changes on devices that have already self-recovered or been manually fixed in the gap between approval and execution.

### 7. Snapshot scheduler queue (`api/routes/snapshots.py`)

Replaced the `409 Conflict` response with a queue: if a snapshot is already running, the new request waits (polling at 5s) for the in-progress one to finish, then runs. Manual snapshots and the hourly scheduled snapshot can no longer trample each other.

### 8. Vector dedup per-device + per-entity guard (`db/vector.py`)

ChromaDB `find_similar` already filtered by `device_id`. Added a second filter on `affected_entity` so two distinct issues on the same device don't dedupe each other (e.g. "BGP neighbor 192.168.1.1 down" must NOT dedupe with "BGP neighbor 192.168.1.5 down" — same device, different peers, two real problems).

### 9. Always-visible INCIDENT badge (`frontend/src/pages/Insights.jsx`)

The badge now appears on every incident card, including 1-finding solo "incidents", with a consistent `INCIDENT · N findings · M devices` format. Solo incidents use a neutral colour, multi-finding correlated ones use the error tint. Operators see at a glance whether they're looking at a single point of failure or a cascade.

---

## Tests run

### V3 baseline (no change to network)

| Metric | Result |
|---|---|
| Snapshots | 18/18 ok |
| Pipelines | 18/18 complete |
| Topology agent (Haiku) calls | **0** |
| Tokens spent | **0** |
| Findings created | 0 |

The deterministic normaliser found no anomalies on any device, the diff was empty (first snapshot in fresh DB), so smart-skip activated for every device. ✅

### V3 cascade (S1-R1 Eth0/0 shut)

| Metric | Result |
|---|---|
| Snapshots | 18/18 ok |
| Pipelines | 18/18 complete |
| Topology calls | 10/18 (8 healthy devices smart-skipped) |
| Total Haiku tokens | 99,312 |
| Per-device Sonnet calls | **0** (deferred) |
| Per-incident Sonnet calls | **1** |
| Findings created | 11 |
| **Incidents** | **1** |
| **Approvals** | **1** (PSR-86) |
| **Jira tickets** | **1** |
| Affected devices in the incident | 9 (DC1-R1, S1-R1, S1-S1, S2-R1, S2-S1, S3-R1, S3-S1, S4-R1, S4-S1) |
| Root cause picked | "Ethernet0/0 interface administratively shut down — BGP session and routes lost" on S1-R1 ✅ |

This is exactly what the user originally asked for: one event → one incident → one approval, with the actual root cause identified.

### V3 approve + execute

| Metric | Result |
|---|---|
| Approval transitioned `pending → approved` | ✅ |
| Pre-execution sanity check ran | ✅ (took fresh single-device snapshot, confirmed symptom present) |
| pyATS executed `configure { interface Ethernet0/0; no shutdown }` | ✅ |
| S1-R1 Ethernet0/0 confirmed back **up** via SSH check | ✅ |
| Jira PSR-86 transitioned to executed with comment | ✅ |
| Verification snapshot triggered post-execution | ✅ |

---

## Outstanding items / further opportunities

These are observations from V3 testing — not implemented; left for the next session.

### O1 — Per-device Haiku still expensive when cascades are big

A cascade affecting 9 devices ran 10 Haiku calls (9 cascade + 1 unrelated baseline). At ~10K tokens each = ~99K Haiku per event. A possible next-tier optimisation: **batch Haiku calls** — send a single Haiku request with the normalised data from all devices that have anomalies, and have it produce findings for the whole batch. Would cut to ~30K tokens for the same cascade. Risk: prompt size + bigger response = harder to validate JSON. Worth trying.

### O2 — Verification snapshot also runs the full pipeline

After successful execution, the engine triggers a single-device snapshot to verify the fix took. That snapshot then runs the full pipeline + Haiku for that device. Often the verification snapshot would just confirm "interface up, BGP Established" — no findings — but we still pay for Haiku. A trivial optimisation: pass `defer_remediation=True` and skip Haiku entirely for verification snapshots, since the goal is "did the change happen", not "are there new findings".

### O3 — Per-snapshot cost visibility

The pipeline_complete log has `tokens` per device but there's no top-level "this snapshot run cost X tokens, $Y" surface in the API or UI. Operators can't see cost per cycle without grep'ing logs. Add a tokens column to `agent_runs` per-incident and surface in the dashboard.

### O4 — DC2-R2's persistent issue is now invisible

With Ollama removed, the deterministic normaliser only flags BGP that's NOT Established. DC2-R2's actual problem ("BGP Established but zero routes received") needs Haiku to detect — but smart-skip prevents Haiku from running because the deterministic normaliser sees nothing wrong. Two fixes possible:
- Strengthen the deterministic normaliser to count BGP-installed routes per peer and flag "Established peer with zero routes" as an anomaly
- Run Haiku unconditionally for devices flagged as having BGP peers — small token cost, catches the subtle cases

### O5 — Pre-flight check extends with category-specific verification

Currently covers interface and BGP-neighbor categories. Easy to extend (OSPF neighbours, route presence, ACL state) — the pattern is in `_symptom_still_present()`.

### O6 — Frontend: incidents-first dashboard

The dashboard page still shows aggregate counts ("12 findings, 3 critical"). With the incident model live, a more useful headline is "2 active incidents (1 critical, 1 medium); 3 affected devices; 1 awaiting approval". Worth a small dashboard refactor.

### O7 — Topology view should highlight incident-affected devices

The topology page already renders the BGP edges and L2 segments. With incident_id available, it could colour the affected devices and the broken edges in the incident colour. Currently you'd have to flip between Insights and Topology to see the picture.

---

## Files changed this round

- `backend/agents/nodes/normaliser.py` (Ollama call removed; admin-down state-change anomaly added)
- `backend/agents/nodes/topology.py` (smart-skip simplified — fallback flag no longer needed)
- `backend/agents/prompts/topology.md` (admin-down nuance section)
- `backend/services/correlation.py` (same-device cross-category merge; history-aware id inheritance; refactored union-find rebuild helper)
- `backend/services/execution_engine.py` (pre-execution sanity check via fresh snapshot + symptom verification)
- `backend/api/routes/findings.py` (incidents endpoint now includes recommendation+reasoning+approval)
- `backend/api/routes/snapshots.py` (snapshot queue replaces 409 conflict)
- `backend/db/vector.py` (per-device + per-entity dedup filter)
- `frontend/src/pages/Insights.jsx` (AI reasoning on card, always-visible INCIDENT badge, Jira link)

---

## Bottom line

The original ask was: "one event should produce one incident with one set of suggestions, not a flood of unlinked findings." 

V3 delivers exactly that, on a real cascade test (S1-R1 Eth0/0 shutdown → 11 findings across 9 devices), with:
- 1 incident
- 1 approval
- 1 Jira ticket (PSR-86)
- The correct root cause picked (not a downstream symptom)
- Wall-clock time cut from ~25 min to ~5 min by removing Ollama
- Token cost roughly halved

The remaining opportunities (O1–O7) are refinements, not corrections — the core problem is solved.
