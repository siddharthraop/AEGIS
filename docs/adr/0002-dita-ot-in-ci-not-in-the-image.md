# ADR 0002: DITA-OT runs in CI, not in the API image

- Status: Accepted · Date: 2026-10-26 · Deciders: Siddharth Rao

## Context
The design's `build_pack` runs DITA-OT with the reader's DITAVAL. A Java runtime and DITA-OT in the image would add
several hundred megabytes against a 100 MB Artifact Registry share.

## Decision
CI builds the three packs' HTML5 and PDF with DITA-OT 4.4 in strict mode from the corpus commit, and the image carries
the output. The API filters with the same DITAVAL rule in Python for the checks, and a test proves both keep the same
topics. A sandbox link or decision changes the manifest and report, not the built topics; the manifest says so.

## Consequences
A small image and fast downloads. A released pack is built fresh by DITA-OT in the release workflow.
