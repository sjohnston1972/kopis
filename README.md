<div align="center">

# 🗡 KOPIS

### AI-Augmented Network Operations with Human-in-the-Loop Remediation

*A digital twin of your network built from live device snapshots, analysed by a tiered swarm of AI agents (Ollama → Haiku → Sonnet → Opus), with remediation commands proposed, approved by a human, and only then executed — every change rolled out through pyATS with automatic post-change verification.*

[![Claude](https://img.shields.io/badge/Claude-claude--opus--4--6-orange?style=flat-square)](https://anthropic.com)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-1c3d5a?style=flat-square)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/Frontend-React%20%2B%20Vite-61DAFB?style=flat-square)](https://react.dev)
[![pyATS](https://img.shields.io/badge/Snapshots-pyATS%20%2F%20Genie-005073?style=flat-square)](https://developer.cisco.com/pyats/)
[![Postgres](https://img.shields.io/badge/Store-PostgreSQL%2016-336791?style=flat-square)](https://www.postgresql.org)
[![ChromaDB](https://img.shields.io/badge/Vector-ChromaDB-7c3aed?style=flat-square)](https://www.trychroma.com)
[![Docker](https://img.shields.io/badge/Deployment-Docker-2496ED?style=flat-square)](https://docker.com)

</div>

---

## What It Does

Kopis builds and maintains a continuously-refreshed digital twin of a network and uses cost-tiered AI agents to surface real problems, propose fixes, and (with your approval) apply them. The name comes from the ancient Greek forward-curved blade — a weapon designed for decisive, close-range action. Kopis cuts through network complexity.

| Capability | Detail |
|---|---|
| **Digital Twin from Live Devices** | pyATS / Genie connects over SSH and `learn()`s the full operational state — interfaces, routing, ARP, BGP, OSPF, VLANs, STP, platform — and stores normalised JSON snapshots in PostgreSQL. |
| **Inventory from Grafana** | No separate inventory to maintain. Kopis pulls monitored devices straight from the Grafana API and generates the pyATS testbed YAML on the fly. |
| **Snapshot Diff** | Recursive structural diff between any two snapshots for the same device — answers "what changed since last night?" without you scrolling configs. |
| **Tiered Agent Pipeline** | A LangGraph state machine: Ollama normalises the raw snapshot → Haiku classifies findings → Sonnet drafts remediation → Opus only escalates when confidence is low. Cheapest model that can do the job wins. |
| **Human-in-the-Loop Approval** | Every remediation goes to an approval queue — web UI **or** Slack interactive buttons. Nothing touches the network until a human says yes. |
| **Jira Ticketing** | Each recommendation auto-creates a KSR ticket with the finding, commands, rollback, and risk. Approve / deny / execute states sync back as transitions + comments. |
| **3-Phase Execution & Verification** | Approved commands run via pyATS, rollback commands are pre-staged, and a fresh snapshot is taken automatically. BGP / OSPF convergence is given time to settle; stragglers are caught in a follow-up sweep. |
| **Closed-Loop Verification** | Findings that triggered a remediation are re-evaluated against the post-execution snapshot — confirmed fixed, still present, or new collateral damage. |
| **Cross-Device Finding Correlation** | The pipeline groups related findings across devices into a single incident so you see "BGP session down between R1 and R2" rather than two disconnected alerts. |
| **Stale-Finding Suppression** | Dashboard metrics filter out findings already remediated or superseded by a newer snapshot — the numbers always reflect *now*. |
| **Agentic Chat Assistant** | In-app chat with multi-turn tool use — ask "show me the routes that disappeared on R3 last night" and it queries snapshots, findings, and topology to answer. |
| **Cost Tracking** | Per-pipeline token usage and per-tier model breakdown, surfaced in the API and dashboard. |
| **Scheduled Snapshots** | Cron-driven snapshot runs via APScheduler; inventory refresh runs on backend startup and on its own schedule. |
| **Stitch-Designed Frontend** | UI designed in Google Stitch, pulled into the codebase via the Stitch MCP server, then built as a React + Vite app served by nginx. |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         KOPIS PLATFORM                              │
│                                                                     │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────────────────┐  │
│  │ Grafana  │───▶│  Inventory   │───▶│   pyATS Snapshot Engine   │  │
│  │ (device  │    │  Service     │    │   (SSH to GNS3 devices)   │  │
│  │  source) │    └──────────────┘    └─────────┬─────────────────┘  │
│  └──────────┘                                  │                    │
│                                                ▼                    │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    LANGGRAPH PIPELINE                       │    │
│  │                                                             │    │
│  │  ┌─────────────┐   ┌─────────────────┐   ┌──────────────┐   │    │
│  │  │ Normaliser  │──▶│ Topology Agents │──▶│ Remediation  │   │    │
│  │  │ (Ollama)    │   │ (Haiku)         │   │ Agents       │   │    │
│  │  └─────────────┘   └─────────────────┘   │ (Sonnet/Opus)│   │    │
│  │                                          └──────┬───────┘   │    │
│  └─────────────────────────────────────────────────┼───────────┘    │
│                                                    ▼                │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    APPROVAL QUEUE                            │   │
│  │       Web UI (approve/deny)  +  Slack  +  Jira (KSR)         │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ▼                                   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │       EXECUTION ENGINE (pyATS / Netmiko + verification)      │   │
│  │       Only runs APPROVED remediations  +  rollback ready     │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌────────────┐  ┌────────────┐                                     │
│  │ PostgreSQL │  │  ChromaDB  │                                     │
│  │ (primary)  │  │ (semantic) │                                     │
│  └────────────┘  └────────────┘                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Docker Containers

| Container | Image | Port | Role |
|---|---|---|---|
| `kopis-backend` | kopis-backend (custom) | 8200 | FastAPI — REST + WebSocket, LangGraph pipeline, pyATS executor |
| `kopis-frontend` | kopis-frontend (custom) | 8201 | React + Vite app, served by nginx |
| `kopis-postgres` | postgres:16-alpine | 5433 | Primary store — devices, snapshots, findings, recommendations, approvals, agent runs |
| `kopis-chromadb` | chromadb/chroma:0.6.3 | 8101 | Vector store — historical findings, snapshot summaries |
| `kopis-stitch-mcp` | kopis-stitch-mcp (custom) | 3333 | Stitch MCP bridge for design pulls — Claude Code attaches via `docker exec` |

External dependencies (not deployed by Kopis): **Grafana** (device inventory source), **Ollama** (Tier 0 normalisation), **Anthropic API** (Tiers 1–3), **Slack**, **Jira Cloud**.

---

## AI Tier Strategy

| Tier | Model | Use Case | Cost Profile |
|---|---|---|---|
| Tier 0 | Ollama (local) | Snapshot normalisation, data reduction, quick anomaly flagging | Free (compute only) |
| Tier 1 | Claude Haiku | Topology classification, severity / confidence scoring | Low |
| Tier 2 | Claude Sonnet | Remediation reasoning, CLI command generation, risk + rollback | Medium |
| Tier 3 | Claude Opus | Escalation when Haiku confidence on a critical finding < 0.7 | High — used sparingly |

Escalation is one-way up. Token usage per tier is tracked per pipeline run and surfaced through `/api/v1/pipeline/stats`.

---

## Pipeline Flow

```
snapshot ──► Normaliser (Ollama)
                  │   normalised_data, anomalies_detected
                  ▼
           Topology Agent (Haiku)
                  │   findings[] with severity + confidence
                  ▼
             ┌────┴────┐
             │         │
   confidence < 0.7    confidence ≥ 0.7
             │         │
             ▼         ▼
      Escalation   Remediation Agent (Sonnet)
       (Opus)       │   recommendations[] + commands + rollback
             │      │
             └──┬───┘
                ▼
      Approval Queue (PENDING)
                │
        ┌───────┴────────┐
   APPROVED            DENIED / EXPIRED
        │
        ▼
  Execution Engine (pyATS)
        │
        ▼
  Post-execution Snapshot
        │
        ▼
  Closed-loop verification — finding cleared? new findings?
```

Every state transition is persisted, Slack + Jira are kept in sync, and the dashboard updates live.

---

## Approval Workflow

States: `PENDING → APPROVED → EXECUTED → (SUCCESS | FAILED)` · `PENDING → DENIED` · `PENDING → EXPIRED` (configurable TTL, default 24h)

- **Web UI** — approval queue page with finding, recommended action, commands, risk level, rollback plan, and agent reasoning. One-click approve / deny with an optional notes field.
- **Slack** — every new recommendation fires a Block Kit message with Approve / Deny / View Details buttons. Approving from Slack updates the same record the UI would.
- **Jira (KSR)** — auto-created ticket per recommendation. Status syncs both ways: approve → transition, execute → comment with output, fail → comment + label.

---

## Getting Started

### Prerequisites

- Docker + Docker Compose
- Anthropic API key
- A running Grafana instance with device targets configured
- SSH credentials for the network devices (read + config-level as needed)
- Jira Cloud project (default key `KSR`) and a Slack webhook (both optional but recommended)

### Setup

```bash
git clone https://github.com/sjohnston1972/kopis.git
cd kopis

cp .env.example .env
# Edit .env — Anthropic key, Grafana URL/key, pyATS creds, Jira, Slack

docker compose up -d

# Backend  → http://localhost:8200/docs   (Swagger UI)
# Frontend → http://localhost:8201
```

### Environment Variables

See [`CLAUDE.md`](CLAUDE.md) for the full annotated list. The essentials:

```env
# Anthropic
ANTHROPIC_API_KEY=
HAIKU_MODEL=claude-haiku-4-5-20251001
SONNET_MODEL=claude-sonnet-4-6
OPUS_MODEL=claude-opus-4-6

# Grafana (inventory source)
GRAFANA_URL=
GRAFANA_API_KEY=

# pyATS device access
PYATS_USERNAME=
PYATS_PASSWORD=

# Ollama (Tier 0)
OLLAMA_URL=http://ollama-host:11434
OLLAMA_MODEL=qwen2.5:14b

# Jira (KSR project)
JIRA_URL=
JIRA_USER_EMAIL=
JIRA_API_TOKEN=
JIRA_PROJECT_KEY=KSR

# Slack
SLACK_WEBHOOK_URL=
SLACK_SIGNING_SECRET=

# Scheduling
SNAPSHOT_SCHEDULE_CRON=0 */6 * * *
APPROVAL_EXPIRY_HOURS=24
```

---

## API

21 endpoints, all under `http://localhost:8200/api/v1/`. Full OpenAPI at `/docs`.

### Devices
| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/devices` | List all devices from inventory |
| `GET` | `/devices/{id}` | Device detail with latest snapshot summary |
| `POST` | `/devices/refresh` | Force inventory refresh from Grafana |

### Snapshots
| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/snapshots` | Trigger snapshot (all devices or one) |
| `GET` | `/snapshots` | List snapshots, paginated |
| `GET` | `/snapshots/{id}` | Full snapshot data |
| `GET` | `/snapshots/{id}/diff` | Diff against previous snapshot for same device |

### Findings & Pipeline
| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/findings` | Filterable by severity / category / device / date |
| `GET` | `/findings/{id}` | Finding + linked recommendation |
| `POST` | `/pipeline/run` | Manually run the LangGraph pipeline against a snapshot |
| `GET` | `/pipeline/status` | Current pipeline status |
| `GET` | `/pipeline/stats` | Token usage, model breakdown, run history |

### Approvals & Execution
| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/approvals` | Pending approvals with full context |
| `POST` | `/approvals/{id}/approve` | Approve — updates Jira + Slack |
| `POST` | `/approvals/{id}/deny` | Deny — updates Jira + Slack |
| `GET` | `/approvals/history` | Executed history |
| `POST` | `/approvals/expire` | Manually expire stale approvals past TTL |
| `POST` | `/execute` / `/execute/{id}` | Execute an approved remediation |

### Topology & Health
| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/topology` | Current topology graph (nodes + edges) |
| `GET` | `/health` | Service health |
| `GET` | `/health/dependencies` | Postgres + ChromaDB + Ollama + Grafana connectivity |

---

## Database

### PostgreSQL (`kopis-postgres`)

| Table | Purpose |
|---|---|
| `devices` | Cached inventory from Grafana — hostname, mgmt IP, platform, tags, last seen |
| `snapshots` | Raw pyATS learned data as JSONB, plus features learned + duration |
| `findings` | Topology-agent output — category, severity, confidence, evidence, links to recommendation |
| `recommendations` | Sonnet/Opus output — commands, rollback commands, risk, reasoning, model used |
| `approvals` | State machine — pending / approved / denied / executed / failed / expired, with operator + channel |
| `agent_runs` | Pipeline execution log — graph state, total tokens, models used, errors |

Schema is managed with Alembic. Current migration: `002` (includes Jira fields on `approvals`).

### ChromaDB (`kopis-chromadb`)

| Collection | Use |
|---|---|
| `historical_findings` | Embedded finding text — semantic "have we seen this before?" lookups during topology analysis |
| `snapshot_summaries` | Embedded per-device snapshot summaries for trend / drift detection |

---

## File Structure

```
kopis/
├── CLAUDE.md                     # Project brief for Claude Code (deep detail)
├── README.md                     # You are here
├── docker-compose.yml
├── .env.example
│
├── backend/
│   ├── main.py                   # FastAPI entry point
│   ├── config.py
│   ├── api/routes/               # 12 route modules — devices, snapshots, findings,
│   │                             #   approvals, execution, pipeline, topology,
│   │                             #   dashboard, schedules, chat, health
│   ├── agents/
│   │   ├── graph.py              # LangGraph assembly
│   │   ├── state.py              # KopisState TypedDict
│   │   ├── nodes/                # normaliser, topology, remediation, escalation
│   │   ├── prompts/              # System prompts per tier
│   │   └── tools/                # Agent tools — device lookup, history, topology query
│   ├── services/                 # inventory, snapshot_engine, testbed_generator, execution_engine
│   ├── integrations/             # grafana, slack, jira, ollama
│   ├── models/                   # Pydantic models
│   └── db/                       # Alembic migrations, schemas, async session
│
├── frontend/                     # React + Vite app (Stitch-designed)
│   ├── src/
│   │   ├── pages/                # Dashboard, Devices, Snapshots, Findings,
│   │   │                         #   Approvals, Pipeline, Executions, Topology,
│   │   │                         #   Insights, Settings
│   │   ├── components/           # Layout, Sidebar, TopNav, ChatPanel, Dialog, StatusChip
│   │   ├── hooks/                # WebSocket + data hooks
│   │   └── api/                  # REST client
│   ├── stitch-screens/           # Raw HTML pulled from Stitch (reference)
│   └── DESIGN.md                 # Lumina design system from Stitch
│
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── nginx/kopis.conf
│   └── stitch-mcp/Dockerfile
│
└── tests/                        # pytest-asyncio — agent nodes, approval state machine, testbed generation
```

---

## Build Sequence

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation — Docker, Postgres, ChromaDB, FastAPI skeleton, Alembic, Pydantic models | done |
| 2 | Inventory + snapshots — Grafana client, testbed generator, pyATS engine, diffs | done |
| 3 | Agent pipeline — LangGraph state, Normaliser → Topology → Remediation → Escalation, pipeline API | done |
| 4 | Approval + execution — full state machine, Slack Block Kit, Jira KSR integration, pyATS executor, verification | done |
| 5 | Frontend — Stitch designs pulled via MCP, React + Vite build, topology viz, static map + detail panel | done |
| 6 | Polish — scheduled snapshots, token / cost dashboard, ChromaDB historical search, comprehensive logging | in progress |

---

## Sibling Project

Kopis shares its homelab Docker infrastructure with **Gladius**, an AI-powered Cisco network *security auditor* (NIST 800-53 / CIS, CVE intelligence, pentest agent). They're entirely separate codebases — Kopis does day-2 operations and remediation; Gladius does posture and audit.

---

<div align="center">

**KOPIS** — AI-Augmented Network Operations · Built with Claude + LangGraph · Runs on Docker

</div>
