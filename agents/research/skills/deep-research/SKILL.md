---
name: deep-research
description: >
  Systematic multi-engine web research and factual investigation. Covers temporal
  grounding with datetime tools, multi-pass search across Tavily, Exa, and Linkup,
  strategic reflection using think_tool, citation verification, gap flagging, and
  persisting synthesized findings to markdown files.
---

# Deep Research Skill

## When to use this skill
Use this skill for any factual investigation, live data lookup, competitive analysis,
academic/technical survey, or when answering questions where the facts need fresh
real-world evidence and multi-engine verification.

---

## Step 1 — Temporal Grounding
Before querying for anything involving "today", "yesterday", "current", "latest", or
recent years:
1. Call `get_current_datetime()`.
2. Inspect the returned date, year, and timezone.
3. Incorporate explicit temporal boundaries (e.g. "2026", "September 2026") into search queries.

---

## Step 2 — Multi-Engine Search Pass
1. Select appropriate search engines based on inquiry type:
   - `tavily_search`: Real-time news, market prices, current events.
   - `exa_search`: Technical docs, research papers, long-form articles, authoritative analyses.
   - `linkup_search`: Structured datasets, licensed content, premium business news.
2. Query at least **2 distinct engines** to corroborate claims across independent sources.

---

## Step 3 — Reflection and Gap Analysis
After receiving search responses:
1. Invoke `think_tool` with your assessment:
   - What key facts are confirmed with high confidence?
   - What questions remain partially answered or contradictory?
   - Is another search pass needed with refined keywords?
2. If gaps remain, execute a targeted follow-up query before finalizing.

---

## Step 4 — Synthesis & Source Attribution
1. Structure the findings clearly: Executive Summary, Key Findings, Detailed Analysis, Gaps/Limitations, Sources.
2. Ensure every claim links back to a source URL with the engine identified.
3. If an output file path was requested by the user/orchestrator (e.g., `research/topic.md`), write the full report using `write_file`.
