# Security policy

## Reporting

Do not open a public issue containing credentials, assessment snapshots,
device names, addresses, configurations, or exploit details. Use the
repository's private GitHub security-advisory reporting channel. If that
channel is unavailable, contact the repository owner privately and provide
only the minimum reproduction needed.

## Supported versions

Security fixes are applied to the current release line. Older releases and
portable bundles should be upgraded rather than treated as independently
supported branches.

## Operational boundary

- Treat device inventories, raw captures, snapshots, generated deliverables,
  AssessHub databases, and execution logs as client-confidential.
- Keep live material under `private-inputs/`, `client-inputs/`, or an external
  engagement store. Those roots are intentionally ignored.
- Never commit credentials. Prefer interactive prompting or the documented
  runtime secret channels.
- Network collection is authorized activity: a bare `cisco-assess` may open
  SSH sessions. Use `--no-collect`, `--compare`, or `--trend` for offline work.
- AssessHub and the MCP socket transports are loopback-only unless a separate
  authenticated deployment boundary is designed and reviewed.

## Supply-chain controls

GitHub Actions dependencies are pinned to immutable commits. Pull-request code
runs on hosted ephemeral runners. Release tags are bound to the project
version and `main`, release archives are verified before installation, and
PyPI promotes the exact GitHub Release assets through OIDC rather than
rebuilding or using a stored upload token.

The CI privacy gate and ignore-policy tests prevent known engagement artifacts
and client markers from re-entering the tracked source tree. These controls
protect new commits; removing sensitive data from existing Git history
requires a separately approved history rewrite and credential/identifier
response plan.
