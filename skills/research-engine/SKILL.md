---
name: research-engine
description: Multi-engine web research — delegates to web_searcher subagent for comprehensive, source-cited data collection using Tavily, Exa, and Linkup.
---

# Research Engine Skill

**Step 1 of 3:** `[research-engine] → analysis-synthesis → report-and-email-delivery` — runs FIRST, never skipped.

## When to Use
Any topic needs researching before responding; user asks for news/current data/live prices; a fact is uncertain; user says "research/look up/search for".

## Process
1. **Check memory** — `search_memory` for prior research on this topic. Time-sensitive topics always need fresh data.
2. **Delegate to web_searcher** — specify BOTH topic and output path: *"Research [topic] and save to research/[topic-slug].md"*. Sophie runs `tavily_search` (real-time), `exa_search` (depth), optionally `linkup_search` (structured), and saves findings with source URLs.
3. **Read the output** — `read_file("research/[topic-slug].md")`. If empty/thin, re-delegate ONCE with a more specific query.
4. **Hand off** — proceed to `analysis-synthesis`. Never present raw search output to the user.

## Quality Gates
- ≥2 search engines per topic; every source has a URL with its engine noted (Tavily/Exa/Linkup).
- If web_searcher fails, retry ONCE with a refined instruction before reporting failure.
