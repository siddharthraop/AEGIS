"""Per-visitor sandbox overlays, the daily model quota and the pack register.

Firestore on Cloud Run (collections aegis_sandbox, aegis_quota, aegis_register); memory locally and in tests.
A sandbox expires 7 days after its last change: Firestore deletes it by TTL on `expires_at`, and the service ignores
an expired one even before Firestore gets to it.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading

log = logging.getLogger("aegis.store")
TTL_DAYS = 7


def _now():
    return dt.datetime.now(dt.timezone.utc)


class Store:
    def __init__(self, use_firestore: bool | None = None):
        self.mem: dict[str, dict] = {}
        self.count: dict[str, int] = {}
        self.register_mem: list[dict] = []
        self.lock = threading.Lock()
        self.db = None
        if use_firestore is None:
            use_firestore = os.environ.get("AEGIS_FIRESTORE") == "1"
        if use_firestore:
            try:
                from google.cloud import firestore
                self.db = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)
                self.fs = firestore
            except Exception as e:  # pragma: no cover - depends on the runtime
                log.warning("Firestore unavailable, using memory: %s", e)
        self.backend = "firestore" if self.db else "memory"

    # -- sandbox -----------------------------------------------------------------------------------------------
    def get(self, sid: str) -> dict | None:
        doc = None
        if self.db:
            try:
                d = self.db.collection("aegis_sandbox").document(sid).get()
                doc = d.to_dict() if d.exists else None
            except Exception as e:  # pragma: no cover
                log.warning("Firestore read failed: %s", e)
        else:
            doc = self.mem.get(sid)
        if not doc:
            return None
        exp = doc.get("expires_at")
        if isinstance(exp, str):
            exp = dt.datetime.fromisoformat(exp)
        if exp and exp < _now():
            return None
        return json.loads(doc["overlay"])

    def put(self, sid: str, overlay: dict):
        doc = {"overlay": json.dumps(overlay), "updated": _now().isoformat(), "expires_at": _now() + dt.timedelta(days=TTL_DAYS)}
        if self.db:
            try:
                self.db.collection("aegis_sandbox").document(sid).set(doc)
                return
            except Exception as e:  # pragma: no cover
                log.warning("Firestore write failed: %s", e)
        with self.lock:
            self.mem[sid] = dict(doc, expires_at=doc["expires_at"].isoformat())

    def delete(self, sid: str):
        if self.db:
            try:
                self.db.collection("aegis_sandbox").document(sid).delete()
            except Exception as e:  # pragma: no cover
                log.warning("Firestore delete failed: %s", e)
        self.mem.pop(sid, None)

    # -- quota -------------------------------------------------------------------------------------------------
    def used(self, kind: str) -> int:
        doc = f"{kind}-{dt.date.today().isoformat()}"
        if self.db:
            try:
                d = self.db.collection("aegis_quota").document(doc).get()
                return int((d.to_dict() or {}).get("count", 0)) if d.exists else 0
            except Exception:  # pragma: no cover
                pass
        return self.count.get(doc, 0)

    def take(self, kind: str) -> int:
        doc = f"{kind}-{dt.date.today().isoformat()}"
        if self.db:
            try:
                ref = self.db.collection("aegis_quota").document(doc)
                ref.set({"count": self.fs.Increment(1), "kind": kind}, merge=True)
                return int(ref.get().to_dict().get("count", 1))
            except Exception as e:  # pragma: no cover
                log.warning("Firestore quota failed: %s", e)
        with self.lock:
            self.count[doc] = self.count.get(doc, 0) + 1
            return self.count[doc]

    # -- register of released, sealed packs --------------------------------------------------------------------
    def register(self, limit: int = 20) -> list[dict]:
        if self.db:
            try:
                q = self.db.collection("aegis_register").order_by("sealed_at", direction="DESCENDING").limit(limit)
                return [d.to_dict() for d in q.stream()]
            except Exception as e:  # pragma: no cover
                log.warning("Firestore register read failed: %s", e)
        return self.register_mem[-limit:][::-1]
