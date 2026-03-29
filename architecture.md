# Kopis — Architecture Reference

## What Is Kopis?

Kopis is a network operations platform that does three things:

1. **Snapshots** your network using pyATS to create a structured, queryable model of every device's state
2. **Analyses** those snapshots using tiered AI agents that spot problems, classify severity, and reason about root cause
3. **Recommends and executes** fixes — but only after a human approves them

Think of it as having a team of increasingly senior network engineers looking at your network 24/7. The junior (Ollama) organises the data. The mid-level engineer (Haiku) spots issues and classifies them. The senior engineer (Sonnet) decides what to do about them. And the principal engineer (Opus) gets called in when nobody else is sure.

---

## Why Not Just Extend Gladius?

Gladius does device audits — it connects to a device, pulls its config, checks for CVEs, and generates a report. That's a **point-in-time, per-device** view.

Kopis does something fundamentally different:

- It snapshots the **entire network state**, not just config
- It reasons **across devices** — "this link is down, and that means these routes are affected"
- It maintains a **historical model** — "this interface has flapped 3 times this week"
- It **acts** on findings (with your permission)

They're complementary tools. Gladius tells you "this device has vulnerabilities." Kopis tells you "this network has problems, here's what to do about them."

---

## The Data Flow (How Everything Connects)

Here's the journey of data through Kopis, step by step:

### Step 1: Where Do Devices Come From?

**Grafana** is the source of truth. Your Grafana instance already monitors your GNS3 lab devices (via SNMP, node_exporter, or however you've set it up). Kopis queries the Grafana API to ask "what devices exist?" and builds its inventory from that.

This means: add a device to Grafana monitoring, and Kopis automatically knows about it. No manual inventory management.

### Step 2: How Does Kopis Talk to Devices?

**pyATS** is the tool that connects to network devices via SSH and pulls structured data. It's Cisco's own testing/automation framework. When pyATS "learns" a device, it runs show commands and parses the output into structured Python objects.

For example, `device.learn('interface')` doesn't just run `show ip interface brief` — it runs multiple commands and builds a complete model of every interface's state: IP address, status, counters, errors, speed, duplex, everything.

Kopis generates the pyATS **testbed file** (a YAML file that tells pyATS how to connect to each device) automatically from the Grafana inventory.

### Step 3: What Happens to Snapshot Data?

The raw pyATS output (big JSON blobs) goes into **PostgreSQL**. Each snapshot is stored with:
- Which device it's from
- When it was taken
- What features were learned
- The full JSON data

PostgreSQL was chosen because:
- It handles JSON natively (JSONB columns) and lets you query inside JSON
- It's relational, so you can easily link snapshots → findings → recommendations → approvals
- You already know it from other projects
- It's rock solid for this kind of structured operational data

### Step 4: How Do Agents Analyse Snapshots?

This is where **LangGraph** comes in. LangGraph is a framework for building workflows where AI agents are the workers. You define a graph with nodes (each node is a processing step) and edges (which decide what happens next).

Here's a teaching moment — LangGraph is different from just "calling an API." In a regular script, you'd do:

```
1. Get data
2. Send to AI
3. Get response
4. Done
```

In LangGraph, you define a **state machine**:

```
1. Data enters the graph with a STATE object
2. Node A processes it, ADDS to the state
3. Based on what Node A found, the graph ROUTES to Node B or Node C
4. Node B processes, ADDS more to the state
5. Eventually the graph reaches an end node
6. The final state contains everything every node produced
```

The key insight: **every agent can see what previous agents found**. The remediation agent doesn't just see raw data — it sees the topology agent's findings, severity classifications, and confidence scores. That context makes it much smarter.

### Step 5: How Does Approval Work?

When the remediation agent produces a recommendation, it goes into an **approval queue**. You see it in two places:

1. **Web UI** — a queue of cards, each showing what was found, what's recommended, what commands will run, and what the rollback plan is
2. **Slack** — a notification with Approve/Deny buttons right in the message

Either approval method updates the same database record. You can approve from your phone via Slack at 2am and it works the same as clicking the button in the web UI.

### Step 6: What Happens After Approval?

The **execution engine** takes approved recommendations and sends the CLI commands to the device — either through pyATS or Netmiko (a simpler SSH library for sending commands).

Critically, after execution, Kopis **automatically takes a fresh snapshot** to verify the change worked. If the post-remediation snapshot still shows the problem, you'll see a new finding about it.

---

## The Model Tier Strategy (Why Multiple AI Models?)

Running everything through Opus would give the best results but would cost a fortune and be slow. Running everything through Ollama would be free but the analysis quality would suffer. So we tier it:

| What | Model | Why |
|---|---|---|
| Organise and clean raw snapshot data | Ollama (local) | It's free, it's fast, and this is mechanical work — extract facts, normalise formats, flag obvious errors. You don't need genius-level AI for "is this counter above threshold?" |
| Analyse device state and classify findings | Haiku | Smart enough to understand network concepts, fast enough to process many devices, cheap enough to run often. This is the workhorse. |
| Decide what to do about findings | Sonnet | Needs deeper reasoning — "should we shut this interface or re-route traffic?" requires understanding consequences. Worth the cost. |
| Handle genuinely complex situations | Opus | The "phone a friend" tier. Multi-device correlation, ambiguous symptoms, conflicting data. Used rarely (target: <20% of analyses). |

### How Escalation Works

The topology agent (Haiku) includes a confidence score with every finding. If it flags something as critical but its confidence is below 70%, it sets a flag: `escalate_to_opus = True`. The LangGraph conditional edge picks this up and routes to the Opus node instead of the Sonnet remediation node.

This means Opus only runs when it's genuinely needed, keeping costs under control.

---

## LangGraph — What You Need to Know

Since this is your first LangGraph project, here are the key concepts:

### State
A Python dictionary (specifically a TypedDict) that flows through the entire graph. Every node reads from it and writes to it. Think of it as a shared clipboard that every agent can read and write to.

### Nodes
Functions that take the state, do something (usually call an AI model), and return updates to the state. Each node is responsible for one job.

### Edges
Rules that decide which node runs next. They can be:
- **Direct**: A always goes to B
- **Conditional**: A goes to B if condition X, otherwise goes to C

### Checkpointing
LangGraph can save the state at each step. If something fails halfway through, you can resume from the last checkpoint instead of starting over. We'll use this with PostgreSQL as the checkpoint store.

### Practical Example

```python
# This is simplified, but shows the pattern
from langgraph.graph import StateGraph

graph = StateGraph(KopisState)

# Add nodes
graph.add_node("normalise", normaliser_node)
graph.add_node("topology", topology_agent_node)
graph.add_node("remediate", remediation_agent_node)
graph.add_node("escalate", escalation_node)

# Add edges
graph.add_edge("normalise", "topology")  # Always: normalise → topology

# Conditional: after topology, decide where to go
graph.add_conditional_edges(
    "topology",
    route_after_topology,  # Function that reads state and returns next node name
    {
        "remediate": "remediate",
        "escalate": "escalate",
        "complete": END
    }
)

graph.add_edge("remediate", END)
graph.add_edge("escalate", "remediate")  # After Opus, still do remediation

app = graph.compile()
```

---

## Infrastructure Notes

### What's Shared with Gladius
- Docker host machine
- Docker network (though Kopis gets its own: `kopis_net`)
- nginx reverse proxy (add a new virtual host for Kopis)
- Cloudflare tunnel (add a new route: kopis.clydeford.net)
- Grafana instance (read-only — Kopis queries it, doesn't modify it)
- Ollama instance (shared inference server)

### What's New for Kopis
- Its own PostgreSQL database (separate from any Gladius DB)
- Its own ChromaDB instance (or a separate collection if sharing an instance)
- Its own FastAPI backend
- Its own frontend

### Network Connectivity Requirements
- Kopis backend containers → Grafana API (HTTP)
- Kopis backend containers → GNS3 device management IPs (SSH, port 22)
- Kopis backend containers → Ollama (HTTP, port 11434)
- Kopis backend containers → Anthropic API (HTTPS, external)
- Kopis backend containers → Slack API (HTTPS, external)
- Kopis backend containers → PostgreSQL (TCP, port 5432)
- Kopis backend containers → ChromaDB (HTTP, port 8000)

### GNS3 Device Access
The GNS3 devices run on sjdebian. Kopis runs in Docker. Docker containers need to be able to SSH into GNS3 device management interfaces. This will likely require:
- Docker network configured with access to the GNS3 management subnet
- Appropriate routing between Docker bridge and GNS3 management network
- Firewall rules allowing SSH from Docker containers to GNS3 devices

Test this connectivity EARLY — it's the kind of thing that can block you for a day.

---

## Cost Estimation

### Per Snapshot Run (assuming 5 devices)

| Step | Model | Est. Tokens | Est. Cost |
|---|---|---|---|
| Normalisation × 5 | Ollama | ~10K each | Free |
| Topology analysis × 5 | Haiku | ~5K each | ~$0.01 |
| Remediation (avg 2 findings) | Sonnet | ~3K each | ~$0.05 |
| Escalation (rare, ~20%) | Opus | ~5K each | ~$0.15 |
| **Typical run total** | | | **~$0.10-0.25** |

### Monthly Estimate (4 snapshots/day)

~$12-30/month for AI inference. Adjust snapshot frequency based on budget tolerance.

These are rough estimates — actual costs depend on how much data pyATS returns per device and how verbose the agent prompts are. The token tracking built into Kopis will give you real numbers quickly.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| GNS3 devices unreachable from Docker | High | Blocks everything | Test connectivity in Phase 1, before any other work |
| pyATS snapshot data too large for LLM context | Medium | Agents get confused | Normaliser node aggressively reduces data; chunk by feature if needed |
| LangGraph learning curve | Medium | Slows development | Start with a minimal 2-node graph, add complexity incrementally |
| Opus escalation rate too high (>20%) | Medium | Cost overruns | Improve topology agent prompts; add more structured analysis rules |
| Approval queue bottleneck (nobody approves) | Low | Recommendations expire unused | Slack notifications with clear, low-friction approval buttons |
| Stitch MCP integration issues | Low | Frontend delayed | Frontend is Phase 5; plenty of time to debug. API works without frontend. |

---

## Naming Conventions

- Database tables: `snake_case` plural (e.g., `findings`, `approvals`)
- API endpoints: `kebab-case` after `/api/v1/`
- Python modules: `snake_case`
- Pydantic models: `PascalCase` (e.g., `Finding`, `Recommendation`)
- Environment variables: `UPPER_SNAKE_CASE`
- Docker services: `kopis-backend`, `kopis-postgres`, `kopis-chromadb`, `kopis-frontend`
