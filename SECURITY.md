# Security Policy

## Supported scope

This repository is a public portfolio/demo project, not a production service. Security fixes are still welcome, especially when they affect:

- Secret handling and accidental credential exposure.
- Authentication or session validation in the demo code.
- Dependency, Docker, or CI configuration that could leak data.

## Reporting a vulnerability

- Do not open a public issue with exploit details or live credentials.
- Prefer a private GitHub security advisory if available for the repository.
- If private advisories are unavailable, contact the repository owner directly through GitHub and share only the minimum detail needed to reproduce the issue safely.

## What to include

- A short description of the issue.
- Impact and affected area.
- Safe reproduction steps.
- Suggested mitigation, if known.

## Response expectations

Because this is a personal portfolio repository, response times are best effort. If you discover an exposed real secret, rotate it immediately before reporting it.
