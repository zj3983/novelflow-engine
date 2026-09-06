---
name: Review Changes
description: Perform a structured code review using change detection and impact
---

## Review Changes

Perform a thorough, risk-aware code review using the knowledge graph.

### Steps

1. Run `detect_changes` to get risk-scored change analysis.
2. Run `get_affected_flows` to find impacted execution paths.
3. For each high-risk function, run `query_graph` with pattern="tests_for" to check test coverage.
4. Run `get_impact_radius` to understand the blast radius.
5. For any untested changes, suggest specific test cases.

### Output Format

Provide findings grouped by risk level (high/medium/low) with:
- What changed and why it matters
- Test coverage status
- Suggested improvements
- Overall merge recommendation

## Token Efficiency Rules
- When the graph is available and current, begin with minimal context for the relevant change. If unavailable or stale, inspect source and callers directly.
- Use `detail_level="minimal"` on all calls. Only escalate to "standard" when minimal is insufficient.
- Use the smallest sufficient context. Expand when evidence is missing; completion depends on the requested result and relevant verification, not a fixed number of tool calls or tokens.
