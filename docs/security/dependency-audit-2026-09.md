# Dependency security audit — 2026-09-26

## Scope and method

This audit starts from the committed tree at `f3a2ebd09095ef662339723cf93d2624aec9d44c`. It checks the exact Node lockfiles (`apps/web/package-lock.json` and `apps/web/pnpm-lock.yaml`) separately, and the production and development closures exported from `uv.lock`. Findings were checked against upstream/GitHub advisories on 2026-09-26, then against the application's dependency paths and code.

The original npm lock reported five vulnerable package paths (four high and one critical in npm's package-level summary). The original pnpm lock reported 28 advisory records in production-visible paths; it already resolved `nanoid` to a fixed version. The original Python production closure and full development closure each reported 14 advisory records representing eight distinct advisories. Both npm and pnpm expose Playwright in the production audit view because Next declares it as an optional peer; the Docker image also copies the full `node_modules` directory.

## Findings and minimal changes

| Dependency path | Original locked version | Updated version | Audit classification and reason |
| --- | --- | --- | --- |
| Direct production `next` | 14.2.35 | 15.5.26 | The original lock includes Next.js advisory paths, including critical findings for Windows-hosted servers and AVIF image optimization. The app uses App Router, so the React Server Components findings match its framework path. The production Dockerfile uses Linux; source/config checks found no `next/image`, `ImageResponse`, Server Actions, rewrites, middleware/proxy, or custom Next server, so those feature/host-specific prerequisites were not found in the checked production configuration. Next.js' current support policy lists 16.x Active LTS and 15.x Maintenance LTS; 14.x is unsupported. The critical advisories are patched at 15.5.24 and their affected ranges include 14.x. No fixed 14.2.x release closes this set. 15.5.26 is the current supported maintenance patch and retains React 18. |
| Direct development `@playwright/test` / optional peer `playwright` | 1.47.2 | 1.55.1 | Patched floor for browser-download TLS certificate verification advisory GHSA-7mvr-c777-76hp. Although declared as a test tool, the optional-peer path is present in production audit views and the Docker image. |
| Transitive production `postcss` through Next | 8.4.31 | 8.5.23 | Patched floor for the source-map path traversal/disclosure and incomplete-fix advisories. Next 15.5.26 still constrains PostCSS to 8.4.31, so npm and pnpm overrides keep both committed Node lockfiles on the patched release. |
| Transitive `nanoid` through PostCSS | npm: 3.3.11; pnpm: 3.3.18 | 3.3.18 | The npm lock was vulnerable to three generator-loop/integer-overflow advisories. The pnpm lock was already at the fixed version. The PostCSS override resolves `nanoid` to 3.3.18 in both lockfiles. |
| Transitive production `starlette` through FastAPI | 1.0.0 | 1.3.1 | Minimum release closing the five audited Starlette advisories (Host validation, `HTTPEndpoint`, Windows `StaticFiles`, request URL parsing, and URL-encoded form limits). |
| Transitive production `anyio` through Starlette/Uvicorn | 4.13.0 | 4.14.2 | Minimum fixed release for GHSA-82r6-8w77-94w6 and GHSA-5p39-cfhj-2xmp. |
| Transitive production `idna` through AnyIO; also development via httpx | 3.11 | 3.15 | Minimum fixed release for GHSA-65pc-fj4g-8rjx. |

The Starlette Host-header advisory is directly applicable to the current application path: `apps/api/main.py` uses `request.url.path` to decide whether runtime-secret endpoints receive body-size and depth checks. The remaining Starlette advisories require patterns not found in the app/API source (`request.form()`, `UploadFile`/`Form`, `HTTPEndpoint`, or `StaticFiles`), but the dependency itself is upgraded to close the lockfile findings. The audited application uses `urllib` for provider connections and does not call AnyIO's affected TCP connector or process-pool APIs directly.

The Next 14-to-15 build check required one source compatibility adjustment: `apps/web/app/projects/[id]/layout.tsx` now awaits Next 15's promised route `params` before passing the same decoded `id` to the existing provider. No other application behavior or dependency family was changed.

## Primary advisory sources

- [Next.js support policy](https://nextjs.org/support-policy) and [September 22, 2026 security update](https://nextjs.org/blog/nextjs-security-update-september-22-2026).
- Next.js [GHSA-2xp9-vwfh-vxw4](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4), [GHSA-p293-qw3h-jr36](https://github.com/vercel/next.js/security/advisories/GHSA-p293-qw3h-jr36), and [GHSA-89xv-2m56-2m9x](https://github.com/vercel/next.js/security/advisories/GHSA-89xv-2m56-2m9x).
- PostCSS [GHSA-fxqj-rqcc-2cmp](https://github.com/postcss/postcss/security/advisories/GHSA-fxqj-rqcc-2cmp) and [GHSA-r28c-9q8g-f849](https://github.com/postcss/postcss/security/advisories/GHSA-r28c-9q8g-f849); Nanoid [GHSA-28wg-ghj8-5hjv](https://github.com/advisories/GHSA-28wg-ghj8-5hjv) and [GHSA-2v37-7h3g-55p8](https://github.com/advisories/GHSA-2v37-7h3g-55p8); Playwright [GHSA-7mvr-c777-76hp](https://github.com/advisories/GHSA-7mvr-c777-76hp).
- Starlette [GHSA-86qp-5c8j-p5mr](https://github.com/advisories/GHSA-86qp-5c8j-p5mr), [GHSA-x746-7m8f-x49c](https://github.com/advisories/GHSA-x746-7m8f-x49c), [GHSA-wqp7-x3pw-xc5r](https://github.com/advisories/GHSA-wqp7-x3pw-xc5r), [GHSA-jp82-jpqv-5vv3](https://github.com/advisories/GHSA-jp82-jpqv-5vv3), and [GHSA-82w8-qh3p-5jfq](https://github.com/advisories/GHSA-82w8-qh3p-5jfq); AnyIO [GHSA-82r6-8w77-94w6](https://github.com/advisories/GHSA-82r6-8w77-94w6) and [GHSA-5p39-cfhj-2xmp](https://github.com/agronholm/anyio/security/advisories/GHSA-5p39-cfhj-2xmp); IDNA [GHSA-65pc-fj4g-8rjx](https://github.com/advisories/GHSA-65pc-fj4g-8rjx).
- pnpm [project settings reference](https://pnpm.io/settings) documents project configuration in `pnpm-workspace.yaml`; this is where the pnpm override is recorded so lock regeneration applies it.

## Verification and residual risk

The updated Node audits (`npm audit`, `npm audit --omit=dev`, and `pnpm audit --prod`) report zero known advisories. `pip-audit` reports no known vulnerabilities for either the production-only or full Python lock closure. `npm ci`, `pnpm install --lockfile-only --frozen-lockfile --ignore-scripts`, `uv lock --check`, and `uv sync --extra dev --frozen` pass. Under Node 20, the Next production build passes type checking and static generation, and the CI-focused mocked Playwright suite passes all 8 tests. On the rebased HEAD, the full Python suite passes with 5,519 passed and 8 skipped in 632.87 seconds; it emitted two warnings (an upstream Starlette `TestClient` deprecation and a temporary-file cleanup warning in `test_cover_image_provider`).

The Next.js project announced another scheduled security release for September 30, 2026, after this audit date. Re-run the advisory checks before merge/deployment, since newly disclosed findings may change the affected ranges or required patch.
