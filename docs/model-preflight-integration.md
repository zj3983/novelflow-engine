# Model capability and context preflight

This note documents the request-time integration with the existing
`model_gateway` capability resolver. It describes how the request is checked,
what happens when the profile is incomplete, and which execution paths use the
shared gate.

## Existing components and integration points

`model_gateway/capabilities.py` remains the source of model identity, cached
runtime observations, capability provenance, tri-state resolution, and the
`preflight_context()` budget classifier. `RuntimeModelGateway` now calls the
request preflight immediately before constructing or invoking a provider
adapter. It does not add a router, scheduler, discovery cache, or remote probe.

The profile identity is the tuple of provider, protocol, normalized base URL,
requested model, and resolved model when known. URL normalization removes
userinfo, query parameters, fragments, and trailing slashes before identity or
diagnostic storage. If endpoint parsing fails, the cache identity uses an
opaque digest; diagnostics independently allowlist URL components and return a
redacted invalid-endpoint label rather than echoing the malformed authority.
Execution preview blocks malformed HTTP(S) endpoints before a provider adapter
is constructed. Runtime observations, provider metadata, official catalog
entries, and user declarations keep their own provenance. Expired records
remain visible as expired evidence but resolve to `unknown` and cannot authorize
a request. When an adapter returns a different resolved model, the response
and prompt-call record retain it, and the existing alias invalidation method
clears stale observations for that alias.

The request estimate uses `ModelRequest.normalized_messages()`, the same message
sequence sent by the adapters. It includes the system instruction and whichever
of `messages` or legacy `prompt` is actually sent; it never counts an unused
legacy prompt a second time. Every unmarked message is required. Callers may
mark whole message indexes as optional; only those whole messages can be
removed by `COMPACT`, followed by a fresh estimate. The Workbench currently
marks no prompt content optional, so it will not trim its task contract or
Canon/context facts to force a request through.

An initial budget classification can be `COMPACT`, `SPLIT`, or `BLOCKED` when
the full optional context and its margin do not fit. If the request has valid
optional indexes and no hard capability, input-shape, output-limit, or adapter
enforcement blocker, preflight removes only those marked messages and
re-estimates the resulting request. It records both pre- and post-compaction
estimates. The compacted request is used only if this second check is `READY`;
otherwise the original request remains unexecuted and the report preserves the
blocking or split reason.

When optional messages are removed and the second estimate passes, the report
keeps `status: COMPACT` and records `recheck_status: READY`; execution then uses
that same compacted request. A failed second estimate remains blocked or split
and never reaches an adapter.

## Budget and capability decisions

Input limit, context window, and maximum output are checked independently.
Input and context estimates use the named `utf8_bytes_div3_v1` heuristic: the
UTF-8 byte length of each normalized message object is divided by three and
rounded up. This is not provider tokenization. The safety margin is the larger
of 128 tokens or 15% of the estimated input. The Workbench shows the estimate
method and margin next to required input, optional input, and reserved output.

When a configured output reservation is absent, the request receives a bounded
4,096-token output reservation. Unknown input and context limits use separate
32,768-token compatibility guards; an unknown maximum output uses a 16,384-token
guard. For protocols with a supported output-enforcement method, the actual
request is bounded to the output reservation. These guards
allow old configurations to continue with a visible compatibility policy; they
are not claims about the provider's real limits. Configure exact limits under
the provider account's per-model capability declaration when available.

The report also states how the adapter enforces the reserved output limit.
HTTP adapters send their native output-limit field. Neither current CLI adapter
exposes a verifiable per-request output cap; requests routed through Codex CLI
or Antigravity CLI are blocked with
`max_output_limit_not_enforceable_by_adapter`, and both adapter/helper
boundaries reject a capped request before launching the CLI. Unknown
enforcement is also blocked. Existing configurations with unknown capabilities
or token limits still use the bounded compatibility guards; a CLI configuration
needs a protocol with an enforceable output limit before model-backed work can
continue.

Unknown optional capabilities keep the existing request behavior and are
reported as unknown; a known unsupported optional parameter may be adjusted
using the existing compatibility rules and the adjustment is recorded. A hard
requirement such as structured JSON output is never removed. If it is known to
be unsupported, the gateway blocks before the adapter. If its state is unknown,
the gateway sends the requirement and relies on the existing parser/schema
validator to reject an invalid response; it does not label the capability as
supported or verified. An unknown required capability is also called out in the
report.

`READY` executes the checked request. `COMPACT` is available only for explicitly
optional whole messages and execution happens only after the compacted request
passes again. `SPLIT` can be requested only by an existing caller that sets the
preflight split permission; this layer never creates sub-tasks or changes
ownership. No current Build Workbench task enables that permission, so an
oversized required request is blocked with a repair action. `BLOCKED` never
constructs or invokes a provider adapter.

## Preview, execution, and persistence boundaries

The Build Workbench `POST .../tasks/{task_id}/preflight` endpoint assembles the
same full-rerun or AI-repair request on the server from the current artifact,
task definition, declared dependencies, and repair scope. It invokes
`RuntimeModelGateway.preflight_resolved()` only; it does not create a run, write
an artifact, or contact a provider. The page shows the returned identity,
limits, provenance, estimates, policy, result, and repair actions. The browser
does not submit a “passed” result or prompt text.

Starting a rerun or repair resolves one runtime settings snapshot and passes
that exact snapshot to the gateway. The gateway repeats the same preflight
against the just-assembled request before adapter creation; preview results are
never trusted for execution. Workbench provider work remains outside the
project lock. Existing source revision, artifact revision, candidate authority,
pre-commit checks, and repair scope remain in force. A preflight failure after a
run has been admitted uses the existing failure transition, clears
`active_run_id`, preserves the accepted artifact and descendants, and leaves a
failed run for recovery/audit.

The same gateway boundary covers Build Workbench orchestration/full reruns and
AI repair, `WorldBuildGraphRunner`, Opening construction and next-volume
planning, continuation planning, and the Character, Director, Writer, and
Consistency/Canon Review runtime adapters. Deterministic work, manual artifact
edits, and candidate confirmation do not call the model gateway and therefore
do not probe capabilities.

A BLOCKED or SPLIT Character or Canon Review preflight is propagated as a task
failure through the provider, agent, and pipeline fallback boundaries. It does
not become a rule-generated Character proposal or the older advisory
`consistency.unavailable` finding. The downstream Director/Writer/FactExtractor
and candidate publication do not run after a Character rejection; after a
Canon Review rejection the writer bundle is not published and FactExtractor
does not run. Correcting the provider/model configuration permits a retry.
Other model transport failures retain their existing advisory fallback
behavior because they are not evidence of a hard preflight rejection or a
Canon contradiction.

Prompt-call logs and API diagnostics store the safe preflight report, not the
private prompt. The report includes counts and safe identity only; it excludes
API keys, Authorization values, credential-bearing URLs, and prompt contents.
Read-only task views display stored reports without resolving profiles or
probing providers. Configuration resolution errors keep distinct reasons such
as `runtime_configuration_unavailable`, `protocol_mismatch`, and
`invalid_base_url`; they are not rewritten as `unsupported_protocol`.

## User-declared configuration

Provider accounts may store a `model_capabilities` object keyed by the exact
configured model name. Each entry may have `capabilities` and `limits`, for
example:

```json
{
  "my-model": {
    "capabilities": { "json_mode": "supported" },
    "limits": {
      "input_token_limit": 64000,
      "context_window": 65536,
      "max_output_tokens": 8192
    }
  }
}
```

These records are labeled `user_declared`, not verified. Old runtime
configuration files that omit `model_capabilities` continue to load with an
empty declaration map and the bounded unknown-profile policy above.

## Verification boundaries

Tests use injected transports and local capability stores. This milestone does
not call a real provider, run a large-context stress test, or certify generated
prose quality. Dependency security review remains a separate task.
