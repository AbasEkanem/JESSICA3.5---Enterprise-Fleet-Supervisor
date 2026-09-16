# Research Findings: Project Management AI Agent Stack

## 1. `create_deep_agent` vs `create_agent` (LangChain)
LangChain is one stack with three rungs [^1][^2]:
- **LangGraph** (runtime) — state machines, checkpointing, streaming, interrupts, HITL. For custom control flow: branching, retries, parallel sub-agents, approval gates.
- **`create_agent`** (LC 1.0 harness) — standard ReAct loop (model + tools + opt-in middleware). For "think → tool → repeat", RAG, simpler agents.
- **`create_deep_agent`** (Deep Agents, built on `create_agent`) — batteries-included for long-horizon autonomous work.

`create_deep_agent` adds, built-in: `write_todos` planning, a filesystem (`ls/read/write/edit/glob/grep/execute`), `task` sub-agents with isolated context, auto-summarization + `MemoryMiddleware` (AGENTS.md) + `SkillsMiddleware`, persistent cross-thread memory, and a HITL layer. `create_agent` has these only as manual opt-ins.

**Recommendation:** start with `create_deep_agent` for a PM agent — multi-step planning, context offloading, delegation, persistent memory, and approval gates are all built-in defaults you can override. Drop to raw LangGraph only when control flow *is* the product. Community: "Deep Agents gives you a car; LangGraph gives you an engine and transmission." [^3][^4]

## 2. Best Free-Tier PM Platforms (2024–2025)
- **Most generous free tier:** ClickUp (unlimited users + core features) and Plane (OSS, no limits self-hosted) [^5][^7].
- **Best API for agents:** Jira (full REST on free) [^10], Linear (GraphQL) [^9], GitHub Projects (GraphQL v2), Plane (REST + MCP emerging).
- **MCP-native:** Notion (official), Wrike [^12], Kanbo [^13], Onplana [^14], Zoho Projects [^6]; most others are community/REST-only.
- **Watch-outs:** Asana free tier shrank to 2 users (Nov 2025) [^5]. Self-hosted OSS (Plane, Leantime, OpenProject, Taiga) remove SaaS limits but need infra [^11].

| Priority | Pick |
|---|---|
| Easiest start, richest free API | **ClickUp** (REST + native AI + unlimited users) |
| Developer-first | **Linear** (GraphQL) or **Plane** (REST + OSS) |
| Already on GitHub/GitLab | **GitHub Projects** or **GitLab** |
| Max control, no lock-in | **Plane** self-hosted (or Leantime/OpenProject/Taiga) |
| MCP-native (agent-first) | **Notion**, **Wrike**, **Kanbo**, **Onplana**, **Zoho** |

## 3. Best Free Production Storage (2024–2025) [^15][^16]
| Provider | Type | Free | Notes |
|---|---|---|---|
| **Supabase** | Postgres + BaaS | 500 MB, unlimited API | Most complete free package (auth/storage/realtime/edge); low lock-in. Pauses after 1wk inactivity. |
| **Neon** | Serverless Postgres | 0.5 GB ×100 projects | Branching, scale-to-zero; ~500ms cold start. |
| **Turso** | Edge SQLite (libSQL) | 5 GB, 500M reads/mo | Edge/low-latency, mobile/IoT. |
| **Cloudflare D1** | Edge SQLite | 5 GB | 100K writes/day; best on Workers. |
| **Upstash** | Serverless Redis/KV | 256 MB, 500K cmds/mo | Caching, rate-limit, sessions; true pay-per-request. |
| **MongoDB Atlas** | Document | 512 MB (M0) | Schema-flexible. |
| **CockroachDB** | Distributed SQL | 10 GiB | Postgres-compat, scales to zero. |
| **Firebase** | Firestore + BaaS | 1 GiB | High lock-in; Storage removed from free Feb 2026. |
| **Appwrite** | Document + BaaS | 2 GB, 75K MAU | Open-source Firebase/Supabase alt. |

**Critical changes:** PlanetScale removed its free tier (Apr 2024 — avoid for new projects) [^17]; Firebase free Storage gone (Feb 2026); Redis went non-OSS (SSPL/RSALv2, Mar 2024 — Valkey/Dragonfly are the OSS forks).

## Summary Stack for a PM Agent
| Layer | Pick | Why |
|---|---|---|
| Framework | `create_deep_agent` | Built-in planning, FS, sub-agents, memory, HITL |
| PM platform | **ClickUp** or **Linear** (SaaS); **Plane** (OSS) | Best free tier + API + AI |
| Database | **Supabase** | Most complete free Postgres package, low lock-in |
| Cache/queue | **Upstash** (Redis + QStash) | Pay-per-request |
| Vector/RAG | **Zilliz Cloud** (managed Milvus) or **Weaviate** | Production vector search |
| Edge reads | **Turso** | Global low-latency |

All three layers compose: Deep Agents → Supabase/Neon for persistence, Upstash for cache, PM platform APIs (REST/GraphQL/MCP) as tools. Production-ready on free tiers with clear upgrade paths.

---
**Sources**
[^1]: [Deep Agents Overview — LangChain Docs](https://docs.langchain.com/oss/python/deepagents/overview)
[^2]: [LangChain vs LangGraph vs Deep Agents](https://dreaming.press/posts/langchain-vs-langgraph-vs-deepagents-harness.html)
[^3]: [LangChain Forum: ordinary vs deep agents](https://forum.langchain.com/t/what-are-the-differences-between-ordinary-intelligent-agents-and-deep-intelligent-agents/3095)
[^4]: [deepagents GitHub](https://github.com/langchain-ai/deepagents)
[^5]: [Best Free PM Software 2026 — ClickUp](https://clickup.com/blog/free-project-management-software)
[^6]: [Best Free AI PM Tools 2026 — DPM](https://thedigitalprojectmanager.com/tools/free-ai-project-management-tools/)
[^7]: [Top OSS PM Tools 2026 — Plane](https://plane.so/blog/top-6-open-source-project-management-software-in-2026)
[^9]: [Linear API Docs](https://developers.linear.app/docs/graphql/overview)
[^10]: [REST API on Jira Free — Atlassian](https://community.atlassian.com/forums/Jira-questions/Use-REST-API-with-Jira-instance-on-Free-Plan/qaq-p/2955396)
[^11]: [OSS ClickUp Alternatives — Leantime](https://leantime.io/click-up-vs-open-source-leantime-taiga-openproject-freedcamp)
[^12]: [Wrike MCP Server](https://developers.wrike.com/mcp-overview/)
[^13]: [Kanbo MCP Server](https://www.kanbo.dev/features/mcp-server)
[^14]: [Onplana MCP — 250+ tools](https://onplana.com/mcp)
[^15]: [DB Free Tier Comparison 2026 — AgentDeals](https://agentdeals.dev/database-free-tier-comparison-2026)
[^16]: [DB Pricing 2026 — BuildMVPFast](https://www.buildmvpfast.com/api-costs/database)
[^17]: [PlanetScale vs Supabase vs Neon — JusDB](https://www.jusdb.com/blog/supabase-vs-planetscale-vs-neon-serverless-database-comparison-2025)
