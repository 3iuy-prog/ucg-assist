"""OSCAL 생성기들이 함께 쓰는 값과 함수."""
from __future__ import annotations

import json
import uuid

OSCAL_VERSION = "1.2.3"
NS = "https://github.com/3iuy-prog/ucg-assist/ns/crossmap"
UUID_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/3iuy-prog/ucg-assist")


def uid(*parts: str) -> str:
    return str(uuid.uuid5(UUID_NS, "|".join(parts)))


def prop(name: str, value: str) -> dict:
    return {"name": name, "ns": NS, "value": value}


def metadata(title: str, date: str, version: str, extra_props: list | None = None) -> dict:
    md = {
        "title": title,
        "last-modified": f"{date}T00:00:00+09:00",
        "version": version,
        "oscal-version": OSCAL_VERSION,
    }
    if extra_props:
        md["props"] = extra_props
    return md


def dump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
