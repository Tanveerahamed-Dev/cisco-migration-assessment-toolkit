# Enhancements master reference

This directory contains the static, interactive reference surface for the
Enhancements repository. It explains the evidence pipeline, major engineering
decisions, data-authority model, trust boundaries, lifecycle gates, repository
areas, verification matrix, and operator entry points.

The site is deliberately not an operational interface. It accepts no evidence,
stores no state, calls no runtime API, uses no analytics or cookies, and does
not become another source of truth. The repository's code, schemas, manifests,
tests, and immutable release evidence remain authoritative.

## Local development

Requires Node.js `>=22.13.0`.

```powershell
npm ci
npm run dev
```

The local preview is served at `http://localhost:3000`.

## Verification

```powershell
npm test
npm run lint
npm audit --audit-level=high
```

`npm test` type-checks the source, performs a production build, renders the
Worker response, checks the semantic content contract, and asserts the surface
remains static and dependency-light. Oxlint enforces correctness,
accessibility, import, Node.js, React, and Next.js rules with warnings treated
as failures. The audit covers runtime and build-time dependencies.

## Design contract

- repository-owned content; no runtime content fetch
- server-rendered semantic HTML with one small interactive client surface
- system fonts and CSS-native visuals; no font or media CDN
- keyboard-operable controls and reduced-motion support
- responsive from narrow mobile screens through large review displays
- exact verification wording: focused proof never implies whole-repository proof
- deployment configuration belongs in `.openai/hosting.json`
