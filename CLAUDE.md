# CLAUDE.md — Kopis

## Project Identity

**Kopis** is an AI-augmented network operations platform that creates a digital twin of a network from device snapshots and uses tiered AI agent swarms to analyse, diagnose, and remediate network issues — with human approval before any changes are executed.

Kopis is a sibling project to **Gladius** (a homelab network audit and intelligence tool). They share Docker infrastructure but are entirely separate codebases. Do not reference or import from Gladius.

The name comes from the ancient Greek forward-curved blade — a weapon designed for decisive, close-range action. Kopis cuts through network complexity.

---

## Current State (as of 2026-03-29)

Phases 1–4 are **complete and running**. Phase 5 (Frontend) is next.

### Running Services
| Container | Image | Port | Status |
|---|---|---|---|
| `kopis-postgres` | postgres:16-alpine | 5433:5432 | Healthy, 6 tables + alembic (migration 002) |
| `kopis-chromadb` | chromadb/chroma:0.6.3 | 8101:8000 | Healthy |
| `kopis-backend` | kopis-backend (custom) | 8200:8000 | Healthy, 21 API endpoints |
| `kopis-frontend` | kopis-frontend (custom) | 8201:80 | Healthy, React + nginx |
| `kopis-stitch-mcp` | kopis-stitch-mcp (custom) | 3333 | Running, connected via user-level MCP config |

### 21 Live API Endpoints (all at `http://localhost:8200/api/v1/`)
`/health`, `/health/dependencies`, `/devices`, `/devices/{id}`, `/devices/refresh`, `/snapshots`, `/snapshots/{id}`, `/snapshots/{id}/diff`, `/findings`, `/findings/{id}`, `/approvals`, `/approvals/{id}/approve`, `/approvals/{id}/deny`, `/approvals/history`, `/approvals/expire`, `/pipeline/run`, `/pipeline/status`, `/pipeline/stats`, `/execute`, `/execute/{id}`, `/topology`

### Next: Phase 5 — Frontend via Stitch MCP
The Stitch MCP container is running and connected. MCP tools are registered in the Claude Code session (configured at user-level in `~/.claude/settings.json`). Use Stitch MCP tools to pull designs and build the React frontend.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python 3.11+) |
| Agent Orchestration | LangGraph |
| Network Snapshots | pyATS / Genie |
| Primary Database | PostgreSQL 16 |
| Vector Search | ChromaDB |
| Local Inference | Ollama (qwen2.5-coder:7b, qwen2.5:14b) |
| Cloud Inference | Anthropic API (Haiku, Sonnet, Opus) |
| Containerisation | Docker / Docker Compose |
| Frontend | Designed in Google Stitch, consumed via Stitch MCP |
| Notifications | Slack (webhooks + interactive messages) |
| Ticketing | Jira Cloud (REST API v2, KSR project) |
| Reverse Proxy | nginx (shared with Gladius) |
| DNS/Access | Cloudflare Tunnels + Zero Trust |

---

## Architecture Overview

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
│  │                    LANGGRAPH PIPELINE                        │    │
│  │                                                             │    │
│  │  ┌─────────────┐   ┌─────────────────┐   ┌──────────────┐  │    │
│  │  │ Normaliser  │──▶│ Topology Agents │──▶│ Remediation  │  │    │
│  │  │ (Ollama)    │   │ (Haiku)         │   │ Agents       │  │    │
│  │  └─────────────┘   └─────────────────┘   │ (Sonnet/Opus)│  │    │
│  │                                          └──────┬───────┘  │    │
│  └─────────────────────────────────────────────────┼───────────┘    │
│                                                    ▼                │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    APPROVAL QUEUE                             │   │
│  │         Web UI (approve/deny)  +  Slack notifications        │   │
│  └──────────────────────────────┬───────────────────────────────┘   │
│                                 ▼                                   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              EXECUTION ENGINE (pyATS / Netmiko)              │   │
│  │              Only runs APPROVED remediations                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌────────────┐  ┌────────────┐                                    │
│  │ PostgreSQL │  │  ChromaDB  │                                    │
│  │ (primary)  │  │ (semantic) │                                    │
│  └────────────┘  └────────────┘                                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
kopis/
├── CLAUDE.md                    # This file
├── docker-compose.yml           # All services
├── .env.example                 # Environment variable template
├── README.md
│
├── backend/
│   ├── main.py                  # FastAPI application entry point
│   ├── config.py                # Settings, env vars, model config
│   ├── requirements.txt
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── snapshots.py     # Snapshot CRUD and trigger endpoints
│   │   │   ├── findings.py      # Finding query and management
│   │   │   ├── approvals.py     # Approval queue endpoints
│   │   │   ├── devices.py       # Device inventory endpoints
│   │   │   ├── topology.py      # Topology view data
│   │   │   └── health.py        # Health check
│   │   └── websockets/
│   │       └── live.py          # WebSocket for real-time UI updates
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── device.py            # Device/inventory models
│   │   ├── snapshot.py          # Snapshot data models
│   │   ├── finding.py           # Finding models (topology agent output)
│   │   ├── recommendation.py   # Remediation recommendation models
│   │   └── approval.py         # Approval record models
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── inventory.py         # Grafana device inventory service
│   │   ├── snapshot_engine.py   # pyATS snapshot orchestration
│   │   ├── testbed_generator.py # Generate pyATS testbed YAML from inventory
│   │   └── execution_engine.py  # Execute approved remediations
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── graph.py             # LangGraph pipeline definition
│   │   ├── state.py             # Shared state schema for the graph
│   │   ├── nodes/
│   │   │   ├── normaliser.py    # Ollama-powered data normalisation
│   │   │   ├── topology.py      # Haiku-powered topology analysis agents
│   │   │   ├── remediation.py   # Sonnet-powered remediation agents
│   │   │   └── escalation.py    # Opus escalation for complex cases
│   │   ├── prompts/
│   │   │   ├── topology.md      # System prompts for topology agents
│   │   │   ├── remediation.md   # System prompts for remediation agents
│   │   │   └── escalation.md    # System prompts for Opus escalation
│   │   └── tools/
│   │       ├── device_lookup.py # Agent tool: query device data
│   │       ├── history.py       # Agent tool: search historical findings
│   │       └── topology_query.py# Agent tool: query topology relationships
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── postgres.py          # PostgreSQL connection and session
│   │   ├── chromadb.py          # ChromaDB client setup
│   │   ├── migrations/          # Alembic migrations
│   │   └── schemas/
│   │       └── tables.sql       # Reference SQL schema
│   │
│   └── integrations/
│       ├── __init__.py
│       ├── grafana.py           # Grafana API client for device inventory
│       ├── slack.py             # Slack webhook + interactive message handler
│       └── ollama.py            # Ollama API client
│
├── frontend/                    # Stitch-generated frontend code
│   └── .gitkeep                 # Populated via Stitch MCP integration
│
├── .claude/
│   └── settings.json            # Project-level MCP server config
├── .env                         # Secrets (gitignored)
├── .env.example                 # Environment variable template
├── .gitignore
│
├── docker/
│   ├── stitch-mcp/
│   │   └── Dockerfile           # Stitch MCP container (Node.js + gcloud)
│   ├── Dockerfile.backend       # Backend container
│   ├── Dockerfile.frontend      # Frontend container (nginx + static)
│   └── nginx/
│       └── kopis.conf           # nginx virtual host config
│
├── tests/
│   ├── test_snapshot_engine.py
│   ├── test_agents.py
│   ├── test_approval_flow.py
│   └── fixtures/
│       └── sample_snapshots/    # Sample pyATS output for testing
│
└── docs/
    ├── architecture.md          # Detailed architecture document
    └── agent-prompts.md         # Agent prompt design notes
```

---

## LangGraph Pipeline Design

### State Schema

The LangGraph state object is the backbone of the entire pipeline. Every node reads from and writes to this shared state. Design it carefully — if the state is wrong, every agent is confused.

```python
from typing import TypedDict, Literal

class KopisState(TypedDict):
    # Input
    snapshot_id: str
    device_id: str
    device_hostname: str
    device_platform: str  # e.g. "iosxe", "nxos", "iosv"
    raw_snapshot: dict     # Full pyATS learned data for this device

    # Normaliser output
    normalised_data: dict  # Cleaned, structured summary of key facts
    interface_summary: list[dict]
    routing_summary: list[dict]
    anomalies_detected: list[dict]  # Quick anomaly flags from normaliser

    # Topology agent output
    findings: list[dict]   # Classified findings with severity and confidence
    # Each finding: {
    #   "id": str,
    #   "category": str,       # e.g. "interface", "routing", "security", "performance"
    #   "severity": str,       # "critical", "high", "medium", "low", "info"
    #   "confidence": float,   # 0.0 - 1.0
    #   "title": str,
    #   "description": str,
    #   "affected_entity": str, # e.g. "GigabitEthernet0/1"
    #   "evidence": dict,      # Supporting data from snapshot
    #   "requires_remediation": bool
    # }

    # Remediation agent output
    recommendations: list[dict]
    # Each recommendation: {
    #   "id": str,
    #   "finding_id": str,     # Links back to the finding
    #   "action": str,         # Human-readable description
    #   "commands": list[str], # Actual CLI commands to execute
    #   "risk_level": str,     # "low", "medium", "high"
    #   "reasoning": str,      # Why this action is recommended
    #   "rollback_commands": list[str],  # How to undo
    #   "model_used": str      # Which model produced this
    # }

    # Control flow
    escalate_to_opus: bool
    processing_stage: Literal["normalise", "topology", "remediation", "escalation", "complete"]
    errors: list[str]
```

### Graph Nodes

1. **Normaliser Node** (Ollama — local, fast, cheap)
   - Receives raw pyATS snapshot JSON
   - Extracts key facts: interface states, routing neighbours, error counters, version info
   - Flags obvious anomalies (interfaces down, high error counts, missing neighbours)
   - Outputs structured summary into `normalised_data`
   - This node should be FAST — it is a data reduction step, not an analysis step

2. **Topology Agent Node** (Haiku — fast, cheap, good enough)
   - Receives normalised data and anomaly flags
   - Analyses device state in context: Is an interface down because it's unused or because something broke?
   - Cross-references with topology relationships: If this link is down, what is affected downstream?
   - Classifies findings by severity and confidence
   - Decides which findings require remediation
   - Sets `escalate_to_opus = True` if confidence on any critical finding is below 0.7

3. **Remediation Agent Node** (Sonnet — deeper reasoning)
   - Receives classified findings that require remediation
   - Generates specific CLI commands to fix each issue
   - Assesses risk of each action
   - Generates rollback commands for every action
   - Writes human-readable reasoning for the approval queue

4. **Escalation Node** (Opus — heavyweight, expensive, use sparingly)
   - Only invoked when `escalate_to_opus = True`
   - Receives the full state including topology agent findings
   - Re-analyses with deeper reasoning
   - Can override topology agent classifications
   - Can generate remediation recommendations directly

### Graph Edges (Conditional Routing)

```
normaliser → topology_agent → [conditional]
                                  ├── if findings require remediation → remediation_agent
                                  ├── if escalate_to_opus → escalation_node
                                  └── if no action needed → complete

remediation_agent → complete
escalation_node → remediation_agent (or complete, if Opus handles it)
```

---

## AI Model Tier Strategy

| Tier | Model | Use Case | Cost Profile |
|---|---|---|---|
| Tier 0 | Ollama (local) | Data normalisation, extraction, quick triage | Free (compute only) |
| Tier 1 | Claude Haiku | Topology analysis, pattern recognition, classification | Low cost per call |
| Tier 2 | Claude Sonnet | Remediation reasoning, command generation, risk assessment | Medium cost per call |
| Tier 3 | Claude Opus | Complex multi-device correlation, ambiguous situations | High cost, use sparingly |

### Model Selection Rules

- **Always start at the lowest viable tier.** Do not use Sonnet for work Haiku can do.
- **Escalation is one-way up.** Haiku can escalate to Sonnet or Opus. Sonnet can escalate to Opus. Never downward.
- **Opus is the exception, not the rule.** If more than 20% of analyses are escalating to Opus, the topology agent prompts need improvement.
- **Track token usage per tier.** Expose this in the API so the operator can monitor costs.

---

## Device Inventory from Grafana

Kopis does NOT maintain its own device inventory. Instead, it pulls device information from Grafana's configured data sources.

### Inventory Service Behaviour

1. Query Grafana API for monitored devices (SNMP targets, node_exporter targets, or custom dashboard variables)
2. Extract: hostname, management IP, device type/platform, location/tags
3. Generate a pyATS testbed YAML file dynamically from this inventory
4. Cache the inventory locally (PostgreSQL) with a configurable TTL
5. Provide a manual refresh endpoint and a scheduled refresh (default: hourly)

### Grafana API Integration

- Use Grafana's REST API (`/api/datasources`, `/api/search`, `/api/dashboards`)
- Authenticate via API key stored in environment variables
- The Grafana instance is already running on the homelab — do not deploy a new one
- Grafana URL and API key are configured via `GRAFANA_URL` and `GRAFANA_API_KEY` env vars

---

## pyATS Snapshot Engine

### Snapshot Lifecycle

1. **Trigger**: Manual (API call) or scheduled (configurable cron via APScheduler)
2. **Testbed Generation**: Build pyATS testbed YAML from current Grafana inventory
3. **Connection**: pyATS connects to each device via SSH
4. **Learning**: Use `device.learn('all')` or selective features: `interface`, `ospf`, `bgp`, `arp`, `vlan`, `spanning_tree`, `routing`, `platform`
5. **Storage**: Raw learned data stored as JSON in PostgreSQL, keyed by device + timestamp
6. **Diff**: Compare against previous snapshot to identify changes (pyATS Diff)
7. **Pipeline Trigger**: Feed new snapshot into the LangGraph pipeline

### pyATS Testbed YAML Structure

```yaml
testbed:
  name: kopis-lab

devices:
  # Dynamically generated from Grafana inventory
  router1:
    os: iosxe
    type: router
    connections:
      defaults:
        class: unicon.Unicon
      ssh:
        protocol: ssh
        ip: 192.168.x.x
        port: 22
    credentials:
      default:
        username: "%ENV{PYATS_USERNAME}"
        password: "%ENV{PYATS_PASSWORD}"
```

### Important pyATS Notes

- Credentials MUST come from environment variables, never hardcoded
- Connection timeouts should be generous for GNS3 devices (they can be slow): 60s connect, 30s command
- Use `learn()` not `parse()` where possible — `learn()` gives normalised object models, `parse()` gives raw CLI output
- Store the pyATS `os` type per device (iosxe, nxos, iosv, etc.) — parsers are os-specific
- Handle connection failures gracefully — a single device being unreachable should not abort the entire snapshot run

---

## Database Design

### PostgreSQL Tables

**devices** — Cached inventory from Grafana
- id, hostname, management_ip, platform, device_type, grafana_source, tags, first_seen, last_seen, last_refreshed

**snapshots** — Raw pyATS snapshot data
- id, device_id (FK), snapshot_data (JSONB), features_learned (array), triggered_by, created_at, duration_seconds

**findings** — Topology agent outputs
- id, snapshot_id (FK), device_id (FK), category, severity, confidence, title, description, affected_entity, evidence (JSONB), requires_remediation, agent_model, tokens_used, created_at

**recommendations** — Remediation agent outputs
- id, finding_id (FK), action_description, commands (JSONB array), rollback_commands (JSONB array), risk_level, reasoning, agent_model, tokens_used, created_at

**approvals** — Human approval records
- id, recommendation_id (FK), status (pending/approved/denied/executed/failed), approved_by, approved_via (web/slack), approved_at, executed_at, execution_result (JSONB), notes

**agent_runs** — Pipeline execution log
- id, snapshot_id (FK), graph_state (JSONB), started_at, completed_at, total_tokens_used, models_used (JSONB), errors (JSONB)

### ChromaDB Collections

**historical_findings** — Embedded findings for semantic search
- Document: finding title + description + evidence summary
- Metadata: device_id, category, severity, timestamp
- Use case: Agents query "have we seen this pattern before?" to provide historical context

**snapshot_summaries** — Embedded snapshot summaries
- Document: normalised data summary per device per snapshot
- Metadata: device_id, timestamp, features
- Use case: Trend analysis and change detection over time

---

## Approval Workflow

### States

```
PENDING → APPROVED → EXECUTED → (SUCCESS | FAILED)
       → DENIED
       → EXPIRED (if not acted on within configurable TTL, default 24h)
```

### Web UI Approval

- Approval queue page shows pending recommendations
- Each card shows: finding summary, recommended action, commands to execute, risk level, rollback plan, agent reasoning
- Approve and Deny buttons with optional notes field
- Approved actions are queued for execution

### Slack Approval

- New recommendations trigger a Slack message via webhook
- Message includes: finding summary, recommended action, risk level
- Interactive message buttons: Approve / Deny / View Details (links to web UI)
- Slack approval updates the same approval record as web UI
- Use Slack Block Kit for message formatting

### Jira Integration

- Every remediation recommendation auto-creates a Jira ticket in the KSR project
- Ticket includes: finding title, severity-mapped priority, device hostname, CLI commands, risk, rollback
- Labels: `kopis`, `severity-{level}`, `device-{hostname}`
- Approval/denial/execution updates are synced back to Jira (transitions + comments)
- `integrations/jira.py` handles all Jira REST API v2 calls
- Env vars: `JIRA_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY`

### Execution

- Only APPROVED recommendations are executed
- Execution uses pyATS or Netmiko to send commands to the device
- Capture command output and store in `execution_result`
- If execution fails, mark as FAILED and alert via Slack + Jira
- After execution, trigger a fresh snapshot to verify the change took effect

---

## Frontend

The frontend is designed in **Google Stitch** and consumed by Claude Code via the **Stitch MCP server**. Do not invent frontend designs — pull them from Stitch.

The Stitch MCP server runs in the `kopis-stitch-mcp` Docker container on the `net_core` network. Claude Code connects to it via `docker exec` (configured in `.claude/settings.json`). When building frontend components, use the MCP tools to retrieve screen designs and code from the active Stitch project.

Stitch will generate a **DESIGN.md** file containing the design system (colours, typography, spacing, components). Reference this file for all frontend styling decisions.

### Frontend Framework

The frontend will be a React application (as generated by Stitch) served as static files via nginx. It communicates with the backend entirely via REST API and WebSocket.

### Key Views (to be designed in Stitch)

1. **Dashboard** — Overview of network health, recent findings, pending approvals
2. **Topology Map** — Visual representation of discovered network topology
3. **Device Detail** — Drill into a specific device's snapshot data, findings, history
4. **Findings Feed** — Chronological feed of all findings, filterable by severity/category/device
5. **Approval Queue** — Pending recommendations with approve/deny actions
6. **Execution Log** — History of executed remediations and their outcomes
7. **Settings** — Snapshot schedule, Grafana connection, Slack webhook, model tier config

---

## API Endpoints

### Devices
- `GET /api/v1/devices` — List all devices from inventory
- `GET /api/v1/devices/{id}` — Device detail with latest snapshot summary
- `POST /api/v1/devices/refresh` — Force refresh from Grafana

### Snapshots
- `POST /api/v1/snapshots` — Trigger a snapshot (all devices or specific device_id)
- `GET /api/v1/snapshots` — List snapshots with pagination
- `GET /api/v1/snapshots/{id}` — Full snapshot data
- `GET /api/v1/snapshots/{id}/diff` — Diff against previous snapshot for same device

### Findings
- `GET /api/v1/findings` — List findings, filterable by severity, category, device, date range
- `GET /api/v1/findings/{id}` — Finding detail with linked recommendation

### Approvals
- `GET /api/v1/approvals` — List pending approvals (with full context: finding, recommendation, device, Jira link)
- `POST /api/v1/approvals/{id}/approve` — Approve a recommendation (updates Jira + Slack)
- `POST /api/v1/approvals/{id}/deny` — Deny a recommendation (updates Jira + Slack)
- `GET /api/v1/approvals/history` — Executed approval history
- `POST /api/v1/approvals/expire` — Manually expire stale approvals past TTL

### Execution
- `POST /api/v1/execute` — Execute an approved remediation (body: `{approval_id}`)
- `POST /api/v1/execute/{approval_id}` — Execute by path param

### Pipeline
- `POST /api/v1/pipeline/run` — Manually trigger the LangGraph pipeline for a snapshot
- `GET /api/v1/pipeline/status` — Current pipeline status
- `GET /api/v1/pipeline/stats` — Token usage, model usage, run history

### Topology
- `GET /api/v1/topology` — Current topology graph (nodes and edges for visualisation)

### Health
- `GET /api/v1/health` — Service health check
- `GET /api/v1/health/dependencies` — PostgreSQL, ChromaDB, Ollama, Grafana connectivity

---

## Environment Variables

```env
# Database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=kopis
POSTGRES_USER=kopis
POSTGRES_PASSWORD=

# ChromaDB
CHROMADB_HOST=localhost
CHROMADB_PORT=8000

# Grafana
GRAFANA_URL=http://grafana:3000
GRAFANA_API_KEY=

# pyATS
PYATS_USERNAME=
PYATS_PASSWORD=
PYATS_CONNECT_TIMEOUT=60
PYATS_COMMAND_TIMEOUT=30

# Ollama
OLLAMA_URL=http://ollama-host:11434
OLLAMA_MODEL=qwen2.5:14b

# Anthropic
ANTHROPIC_API_KEY=
HAIKU_MODEL=claude-haiku-4-5-20251001
SONNET_MODEL=claude-sonnet-4-6
OPUS_MODEL=claude-opus-4-6

# Jira
JIRA_URL=https://your-org.atlassian.net
JIRA_USER_EMAIL=
JIRA_API_TOKEN=
JIRA_PROJECT_KEY=KSR

# Slack
SLACK_WEBHOOK_URL=
SLACK_SIGNING_SECRET=

# Application
SNAPSHOT_SCHEDULE_CRON=0 */6 * * *
APPROVAL_EXPIRY_HOURS=24
LOG_LEVEL=INFO
```

---

## Development Guidelines

### Code Style
- Python: Follow PEP 8, use type hints everywhere
- Use `async/await` for all I/O operations (database, HTTP, pyATS where possible)
- Use Pydantic v2 models for all API request/response schemas
- Use SQLAlchemy 2.0 async for database operations
- Use Alembic for database migrations

### Error Handling
- Never let a single device failure crash the pipeline
- Log all errors with structured logging (structlog or loguru)
- Agent errors should be captured in the `errors` field of the graph state
- API errors return proper HTTP status codes with JSON error bodies

### Testing
- Write tests for agent nodes using sample snapshot fixtures
- Test the approval state machine transitions
- Test pyATS testbed generation from mock Grafana data
- Use pytest with async support (pytest-asyncio)

### Security
- No credentials in code, ever — all from environment variables
- pyATS testbed credentials use `%ENV{}` syntax
- API endpoints should support API key authentication (for Slack callbacks)
- Sanitise all device command output before storing (strip passwords from show run, etc.)

### Docker
- Each service gets its own container: backend, PostgreSQL, ChromaDB, frontend (nginx), stitch-mcp
- All containers join the `net_core` external Docker network (shared across the homelab)
- Grafana and Ollama are EXTERNAL services — connect to them, do not deploy them
- Volume mount for PostgreSQL data persistence
- Health checks on all containers
- All secrets live in `.env` (gitignored), with `.env.example` as template

### Stitch MCP Container
- Container `kopis-stitch-mcp` runs Node.js 22 with `@_davideast/stitch-mcp` and `google-cloud-cli`
- Entrypoint runs `supergateway` bridging `stitch-mcp proxy` stdio to SSE on port 3333
- Claude Code connects via `docker exec -i kopis-stitch-mcp stitch-mcp proxy` (configured at user-level in `~/.claude/settings.json`)
- Authenticated via `STITCH_API_KEY` env var from `.env`
- gcloud credentials persisted in `stitch-gcloud` Docker volume

---

## Build Sequence

When building Kopis, follow this order. Items marked [DONE] are implemented and running.

### Phase 1: Foundation [DONE]
1. [DONE] Docker Compose with PostgreSQL and ChromaDB
2. [DONE] FastAPI skeleton with health check endpoint
3. [DONE] Database schema and Alembic migrations (002 applied — includes Jira fields)
4. [DONE] Pydantic models for all entities

### Phase 2: Inventory & Snapshots [DONE]
5. [DONE] Grafana API client and inventory service
6. [DONE] pyATS testbed generator from inventory
7. [DONE] Snapshot engine — connect, learn, store
8. [DONE] Snapshot API endpoints (with diff)
9. [DONE] Snapshot diff functionality (recursive dict comparison)

### Phase 3: Agent Pipeline [DONE]
10. [DONE] LangGraph state schema (`agents/state.py`)
11. [DONE] Normaliser node — Ollama (Tier 0, local)
12. [DONE] Topology agent node — Haiku (Tier 1)
13. [DONE] Remediation agent node — Sonnet (Tier 2)
14. [DONE] Escalation node — Opus (Tier 3)
15. [DONE] Graph assembly with conditional edges (`agents/graph.py`)
16. [DONE] Pipeline API endpoints (run, status, stats)

### Phase 4: Approval & Execution [DONE]
17. [DONE] Approval queue — full lifecycle (pending/approved/denied/executed/failed/expired)
18. [DONE] Slack integration — Block Kit notifications for findings + approval requests
19. [DONE] Jira integration — auto-creates KSR tickets, syncs transitions + comments
20. [DONE] Execution engine — pyATS command execution with rollback support
21. [DONE] Post-execution verification snapshot (auto-triggered)

### Phase 5: Frontend [DONE]
22. [DONE] Pull designs from Stitch via MCP (5 screens + Lumina design system)
23. [DONE] Build React frontend from Stitch output (Vite + React Router + Tailwind)
24. WebSocket integration for live updates (stub ready, needs backend wiring)
25. [DONE] Topology visualisation (static topology map with device detail panel)
26. [DONE] Dockerfile.frontend (nginx + static files, port 8201)

### Phase 6: Polish
27. Scheduled snapshots (APScheduler)
28. Token usage tracking and cost dashboard
29. Historical finding search via ChromaDB
30. Comprehensive error handling and logging
