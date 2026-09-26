# Live API and browser integration suite

This dedicated suite exercises the file-project workflow through a real local FastAPI process and a real Next.js process, with Playwright driving the browser. Browser API calls are not intercepted: the tests require a response marker from the test server and matching request records in its isolated log.

## Run

The default Playwright config explicitly excludes `tests/integration/**`, so `npx playwright test --list` and ordinary page tests do not import this suite or require any `INTEGRATION_*` variables. The dedicated config collects the two integration tests through the launcher below.

From `apps/web`, install the web dependencies if needed, then run the dedicated launcher:

```powershell
npm ci
npx playwright install chromium
.\run-live-api-integration.ps1
```

The API process uses the Python environment already configured for this repository. It is launched on `127.0.0.1:8187`; Next.js is launched on `127.0.0.1:3187`. Override those ports with `INTEGRATION_API_PORT` and `INTEGRATION_WEB_PORT` if either is occupied. The dedicated config refuses to reuse an existing server. The launcher creates one unique run root before Playwright starts so the API, browser worker, fixture, logs, and report all use the same isolated directory.

Each run creates a fresh `novelflow-live-api-e2e-*` directory under the operating system's temporary directory. Project files, the runtime database and config, request/audit logs, traces, screenshots, and Playwright output are kept there. The servers receive only that directory as their allowed file-project root. The test config sets `NOVELFLOW_E2E_SYNTHETIC=1`; the dedicated FastAPI entrypoint refuses to import unless this explicit test-only flag is present.

## Synthetic boundary

The FastAPI process uses the normal application routes and persistence, but replaces the model gateway, Opening Direction generator, and chapter engine at their injection seams. Fixtures are deterministic and record task IDs and chapter outcomes in the isolated audit log. They never contact a model provider and do not use credentials. The candidate generator emits one deliberate hard Canon blocker for the first chapter-one candidate, then a clean replacement candidate.

The second test seeds a separate fixture labeled `SYNTHETIC VALID END-OF-VOLUME FIXTURE`. It is built from repository test helpers, confirms exactly chapters 1–50 in a disposable project, and has a valid planned second volume covering chapters 51–60. This verifies the cross-volume UI/API continuation at that boundary. It does not claim to validate arbitrary real-novel end-of-volume states, real prose quality, or any protected project.

The suite covers project creation, initial Opening Graph planning, candidate generation, blocked confirmation with pending-candidate preservation, human confirmation advancing once, refresh recovery and next-chapter continuation, plus next-volume extension from the labeled fixture. It complements unit and API tests; it does not repeat their detailed validator coverage.
