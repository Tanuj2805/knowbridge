"""Thin OpenFGA client over its HTTP API.

Plain HTTP keeps the requests readable in logs and avoids SDK version drift.
"""

import hashlib
import json
import logging
import threading
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AppState

log = logging.getLogger(__name__)

STORE_NAME = "knowbridge"
MAX_WRITE = 100  # OPENFGA_MAX_TUPLES_PER_WRITE default
MAX_BATCH_CHECK = 50  # OPENFGA_MAX_CHECKS_PER_BATCH_CHECK default


def _direct(*types: str) -> dict:
    out = []
    for t in types:
        if "#" in t:
            typ, rel = t.split("#")
            out.append({"type": typ, "relation": rel})
        else:
            out.append({"type": t})
    return {"directly_related_user_types": out}


def _union(*relations: str) -> dict:
    return {"union": {"child": [{"computedUserset": {"relation": r}} for r in relations]}}


def _ttu(tupleset: str, relation: str) -> dict:
    return {
        "tupleToUserset": {
            "tupleset": {"relation": tupleset},
            "computedUserset": {"relation": relation},
        }
    }


# JSON form of infra/openfga/model.fga.
AUTHORIZATION_MODEL = {
    "schema_version": "1.1",
    "type_definitions": [
        {"type": "user"},
        {
            "type": "project",
            "relations": {
                "admin": {"this": {}},
                "approver": {"this": {}},
                "leaver": {"this": {}},
                "successor": {"this": {}},
                "viewer": {"this": {}},
                "member": _union("admin", "approver", "leaver", "successor", "viewer"),
            },
            "metadata": {
                "relations": {
                    r: _direct("user")
                    for r in ("admin", "approver", "leaver", "successor", "viewer")
                }
            },
        },
        {
            "type": "source",
            "relations": {"project": {"this": {}}, "reader": {"this": {}}},
            "metadata": {
                "relations": {
                    "project": _direct("project"),
                    "reader": _direct("user", "project#member"),
                }
            },
        },
        {
            "type": "label",
            "relations": {"cleared": {"this": {}}},
            "metadata": {
                "relations": {
                    "cleared": _direct(
                        "user", "project#member", "project#admin", "project#approver"
                    )
                }
            },
        },
        {
            "type": "evidence",
            "relations": {
                "source": {"this": {}},
                "label": {"this": {}},
                "viewer": {
                    "intersection": {"child": [_ttu("source", "reader"), _ttu("label", "cleared")]}
                },
            },
            "metadata": {
                "relations": {"source": _direct("source"), "label": _direct("label")}
            },
        },
    ],
}

MODEL_HASH = hashlib.sha256(json.dumps(AUTHORIZATION_MODEL, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class TupleKey:
    user: str
    relation: str
    object: str

    def as_dict(self) -> dict:
        return {"user": self.user, "relation": self.relation, "object": self.object}


class OpenFGA:
    def __init__(self, base_url: str) -> None:
        self.http = httpx.Client(base_url=base_url, timeout=10)
        self.store_id: str | None = None
        self.model_id: str | None = None
        self._lock = threading.Lock()

    # --- bootstrap ------------------------------------------------------

    def ensure_ready(self, db: Session) -> None:
        """Find or create the store, and write the model if it changed."""
        if self.store_id and self.model_id:
            return
        with self._lock:
            if self.store_id and self.model_id:
                return
            state = db.get(AppState, "openfga") or AppState(key="openfga", value={})
            store_id = state.value.get("store_id")
            if store_id and self.http.get(f"/stores/{store_id}").status_code != 200:
                store_id = None
            if not store_id:
                r = self.http.post("/stores", json={"name": STORE_NAME})
                r.raise_for_status()
                store_id = r.json()["id"]
                state.value = {}
            model_id = state.value.get("model_id")
            if not model_id or state.value.get("model_hash") != MODEL_HASH:
                r = self.http.post(
                    f"/stores/{store_id}/authorization-models", json=AUTHORIZATION_MODEL
                )
                r.raise_for_status()
                model_id = r.json()["authorization_model_id"]
                log.info("openfga: wrote authorization model %s", model_id)
            state.value = {"store_id": store_id, "model_id": model_id, "model_hash": MODEL_HASH}
            db.merge(state)
            db.commit()
            self.store_id, self.model_id = store_id, model_id

    # --- tuples ---------------------------------------------------------

    def write(self, writes: list[TupleKey] = (), deletes: list[TupleKey] = ()) -> None:
        writes, deletes = list(writes), list(deletes)
        while writes or deletes:
            w, writes = writes[:MAX_WRITE], writes[MAX_WRITE:]
            room = MAX_WRITE - len(w)
            d, deletes = deletes[:room], deletes[room:]
            body: dict = {"authorization_model_id": self.model_id}
            if w:
                body["writes"] = {"tuple_keys": [t.as_dict() for t in w], "on_duplicate": "ignore"}
            if d:
                body["deletes"] = {"tuple_keys": [t.as_dict() for t in d], "on_missing": "ignore"}
            r = self.http.post(f"/stores/{self.store_id}/write", json=body)
            if r.status_code >= 400:
                raise RuntimeError(f"openfga write failed: {r.status_code} {r.text[:300]}")

    def _batch(self, chunk: list[TupleKey]) -> list[bool | None]:
        """allowed / denied per check, or None when OpenFGA returned an error for it."""
        body = {
            "authorization_model_id": self.model_id,
            "checks": [{"tuple_key": c.as_dict(), "correlation_id": str(n)} for n, c in enumerate(chunk)],
        }
        r = self.http.post(f"/stores/{self.store_id}/batch-check", json=body)
        r.raise_for_status()
        res = r.json().get("result", {})
        out: list[bool | None] = []
        for n in range(len(chunk)):
            item = res.get(str(n))
            if item is None or item.get("error"):
                out.append(None)
            else:
                out.append(bool(item.get("allowed")))
        return out

    def batch_check(self, checks: list[TupleKey], retries: int = 2) -> list[bool]:
        """Errors are retried, then treated as "denied" (fail closed) and logged."""
        results: list[bool | None] = []
        for i in range(0, len(checks), MAX_BATCH_CHECK):
            results.extend(self._batch(checks[i : i + MAX_BATCH_CHECK]))
        for _ in range(retries):
            failed = [n for n, ok in enumerate(results) if ok is None]
            if not failed:
                break
            for j in range(0, len(failed), MAX_BATCH_CHECK):
                idx = failed[j : j + MAX_BATCH_CHECK]
                for n, ok in zip(idx, self._batch([checks[k] for k in idx]), strict=True):
                    results[n] = ok
        errored = sum(1 for ok in results if ok is None)
        if errored:
            log.warning("openfga: %s of %s checks errored after retries; treated as denied", errored, len(checks))
        return [bool(ok) for ok in results]


_client: OpenFGA | None = None


def client() -> OpenFGA:
    global _client
    if _client is None:
        _client = OpenFGA(get_settings().openfga_api_url)
    return _client
