# ADR 0001: A sandbox overlay, never a write to the source

- Status: Accepted · Date: 2026-10-26 · Deciders: Siddharth Rao

## Context
Visitors must be able to approve links and record decisions, but the DITA source is the evidence. A public page that
changed it would destroy the thing AEGIS proves.

## Decision
A visitor's actions are an overlay, stored per sandbox id in Firestore with a 7-day TTL, applied in memory on top of
the corpus. Everything the overlay adds is labelled "sandbox" in the page, the manifest and the report. Sandbox packs
are hashed but never sealed. The real flow (issue, report, release by a code owner, seal) runs in GitHub Actions.

## Consequences
The checks run on one code path for both. An overlay can't fake a Git approval: `check_approval` reads only the index.
