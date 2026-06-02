# Changelog

All notable changes to this portfolio/demo repository will be documented in this file.

## [0.1.0] - 2026-06-02

### Added
- Public repository hygiene files: `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`, and `SECURITY.md`.
- GitHub Actions CI workflow for lint, tests, import smoke, wheel build, and Docker build validation.
- Import smoke coverage for `app.api.main`.

### Changed
- Narrowed Ruff enforcement to release-safe checks: `E9`, `F`, and `I`.
- Reworked `README.md` into the canonical portfolio release entrypoint with verified setup and validation steps.
- Switched `.env.example` to local-safe placeholder defaults and documented secret-handling rules.
- Updated Docker/bootstrap configuration so local development defaults differ cleanly from Docker Compose overrides.

### Notes
- This release is intentionally positioned as a public portfolio/demo project.
- No hosted deployment or PyPI publication is included in `v0.1.0`.
