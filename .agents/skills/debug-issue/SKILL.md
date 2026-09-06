---
name: Debug Issue
description: Systematically debug issues using graph-powered code navigation
---

## Debug Issue

Use the knowledge graph to systematically trace and debug issues.

### Steps

1. Use `semantic_search_nodes` to find code related to the issue.
2. Use `query_graph` with `callers_of` and `callees_of` to trace call chains.
3. Use `get_flow` to see full execution paths through suspected areas.
4. Run `detect_changes` to check if recent changes caused the issue.
5. Use `get_impact_radius` on suspected files to see what else is affected.

### Tips

- Check both callers and callees to understand the full context.
- Look at affected flows to find the entry point that triggers the bug.
- Recent changes are the most common source of new issues.

## Token Efficiency Rules
- When the graph is available and current, begin with minimal context for the relevant change. If unavailable or stale, inspect source and callers directly.
- Use `detail_level="minimal"` on all calls. Only escalate to "standard" when minimal is insufficient.
- Use the smallest sufficient context. Expand when evidence is missing; completion depends on the requested result and relevant verification, not a fixed number of tool calls or tokens.
