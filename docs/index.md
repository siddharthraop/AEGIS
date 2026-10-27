# AEGIS developer docs

The generate page is the front door: pick a system and AEGIS builds the authority pack and a downstream pack and
measures them. AEGIS turns the Gemma evidence set in dita-corpus into an evidence pack for one reader, and proves that each
requirement is covered, current and approved, or names it as a gap. These pages are for people who run, change or
extend it. For using AEGIS, see the [user help](https://siddharthraop.github.io/AEGIS/help/) and the
[user guide (PDF)](https://siddharthraop.github.io/AEGIS/help/aegis-user-guide.pdf).

AEGIS is a documentation tool. It isn't legal advice, and it doesn't decide whether an obligation applies.

```{toctree}
:maxdepth: 2

dev/architecture
dev/mvp-flow
dev/local-development
dev/testing
dev/deploying
adr/index
```
