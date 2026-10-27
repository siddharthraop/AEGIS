# ADR 0004: The API service serves the site

- Status: Accepted · Date: 2026-10-27 · Deciders: Siddharth Rao

## Context
The first build split the product in two. The site ran on GitHub Pages and called the API on Cloud Run by its full URL.
A working demo then depended on a Pages source setting, the API deploy, CORS and a service URL written into the page.
The first deploy showed the cost: the URL in the page pointed at a service that did not exist.

## Decision
`api/main.py` mounts `site/` at `/` after every `/api` route. The generate page, the sandbox and Ask are served from the
same origin as the API, so calls are same-origin and one URL is the whole product. `site/assets/config.js` picks the
API: the full service URL on `github.io`, an empty string everywhere else. Pages still publishes the design document,
the help and these docs.

## Consequences
One thing to deploy and one URL to share. No CORS on the main path. The image carries the `site/` files. The Pages copies
of the sandbox and Ask still work because they call the service by its full URL, which must be kept current in
`config.js`.
