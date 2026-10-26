"""Command line for CI: run the checks for a reader, build a pack, and record a release.

    python -m aegis.cli check --reader authority
    python -m aegis.cli pack --reader authority --out out [--release-by LOGIN --reason TEXT --request URL]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from .engine import READERS, Engine, empty_overlay, pack_id


def summary_md(res: dict, man: dict | None = None) -> str:
    lines = [f"**{res['reader_info']['pack']}** · {res['reader_info']['set']} · corpus `{res['source']['commit']}` · "
             f"profile `{res['source']['profile']}` · status **{res['status']}**", "",
             "| Check | Result |", "|---|---|"]
    for c in res["checks"]:
        lines.append(f"| `{c['name']}` | {c['passed']}/{c['total']} {'pass' if c['ok'] else '· ' + str(len(c['findings'])) + ' findings'} |")
    gaps = [r for r in res["requirements"] if not r["covered"]]
    if gaps:
        lines += ["", "**Gaps:** " + ", ".join(f"`{r['id']}` {r['title']}" for r in gaps)]
    block = [f for f in res["findings"] if not f.get("decidable")]
    if block:
        lines += ["", "**Blocks release:**"] + [f"- {f['reason']}" for f in block]
    if man:
        lines += ["", f"Pack `{man['pack_id']}` · manifest sha256 `{man['manifest_sha256']}`"]
    lines += ["", "_AEGIS is a documentation tool. It isn't legal advice, and it doesn't decide whether an obligation applies._"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="aegis")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "pack"):
        p = sub.add_parser(name)
        p.add_argument("--reader", choices=list(READERS), required=True)
        p.add_argument("--out", default="out")
        p.add_argument("--release-by")
        p.add_argument("--reason", default="")
        p.add_argument("--request")
    a = ap.parse_args(argv)
    eng = Engine.default()
    ov = empty_overlay()
    res = eng.run(a.reader, ov)
    if a.release_by:
        # The releaser records one decision, with their reason, for every finding that can take one.
        if res["status"] == "blocked":
            print(summary_md(res))
            print("::error title=Release refused::the pack is blocked; fix the source first")
            return 2
        today = dt.date.today().isoformat()
        ov["decisions"] = {f["id"]: {"choice": "release-with-gap", "reason": a.reason or "Released with the findings recorded.",
                                     "by": a.release_by, "date": today} for f in res["findings"] if f.get("decidable")}
        res = eng.run(a.reader, ov)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.md").write_text(summary_md(res), encoding="utf-8")
    if a.cmd == "check":
        print(summary_md(res))
        return 0
    pid = pack_id(a.reader)
    released = {"by": a.release_by, "request": a.request, "date": dt.date.today().isoformat()} if a.release_by else None
    data, man = eng.build_zip(res, pid, sandbox=False, released=released)
    (out / f"{pid}.zip").write_bytes(data)
    (out / "manifest.json").write_text(json.dumps(man, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(summary_md(res, man), encoding="utf-8")
    (out / "pack.env").write_text(f"PACK_ID={pid}\nMANIFEST_SHA256={man['manifest_sha256']}\nSTATUS={res['status']}\n")
    print(summary_md(res, man))
    return 0


if __name__ == "__main__":
    sys.exit(main())
