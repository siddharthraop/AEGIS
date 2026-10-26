# ADR 0003: The approval index is built at build time

- Status: Accepted · Date: 2026-10-26 · Deciders: Siddharth Rao

## Context
`check_approval` needs, for each topic, the pull request that merged its last change and who approved it. Calling the
GitHub API on every page view would hit rate limits and make results depend on the network.

## Decision
`scripts/approval_index.py` writes `data/approvals.json` in CI and the image carries it. A scheduled workflow rebuilds
it and redeploys when it changes. Code owners come from the corpus's `CODEOWNERS`; the last matching pattern wins.

## Consequences
The page shows approvals as of the index's timestamp, which the health endpoint reports. The Gemma topics were first
committed directly, so they fail until a reviewed pull request merges a change to them; the corpus has a workflow that
opens those pull requests.
