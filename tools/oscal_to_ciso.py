#!/usr/bin/env python3
"""OSCAL catalog·profile·mapping-collection → CISO Assistant 라이브러리 YAML 변환.

catalog 하나는 framework 라이브러리 하나가 된다. catalog 의 group 은 평가하지 않는 상위 노드,
control 은 평가 노드가 된다. 그 catalog 를 import 하는 profile(include-controls 의 with-ids 만 지원)은
framework 의 implementation group 이 되고, 각 평가 노드에는 자신이 속한 group 이 붙는다. mapping-collection 의 mapping 하나는
requirement_mapping_set 라이브러리 하나가 된다. 관계 값은 아래 표로만 바꾸고,
표에 없는 값(equivalent-to, no-relationship)은 CISO Assistant 행에서 빼고 보고서에 남긴다.

  OSCAL            CISO Assistant (source 를 target 과 비교한 관계, 방향 같음)
  equal-to      →  equal
  subset-of     →  subset
  superset-of   →  superset
  intersects-with → intersect

사용:
  python3 tools/oscal_to_ciso.py <OSCAL 폴더> <출력 폴더>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

import outdir

URN = "urn:3iuy:risk"
PROVIDER = "3iuy-prog/ucg-assist"
PACKAGER = "3iuy-prog/ucg-assist"
NS = "https://github.com/3iuy-prog/ucg-assist/ns/crossmap"

RELATIONSHIP_MAP = {
    "equal-to": "equal",
    "subset-of": "subset",
    "superset-of": "superset",
    "intersects-with": "intersect",
}


def _prop(obj: dict, name: str) -> str | None:
    for p in obj.get("props", []):
        if p["name"] == name:
            return p["value"]
    return None


VERSION_RE = re.compile(r"-(\d{4})-(\d{2})-(\d{2})-r(\d{2})$")


def _version(md: dict) -> int:
    # metadata.version "<이름>-YYYY-MM-DD-rNN" → YYYYMMDDNN.
    # CISO Assistant 는 version 이 커질 때만 라이브러리를 갱신한다.
    m = VERSION_RE.search(md["version"])
    if not m:
        raise ValueError(f"알 수 없는 metadata.version 형식입니다: {md['version']!r}")
    return int("".join(m.groups()))


def node_urn(slug: str, control_id: str) -> str:
    return f"{URN}:req_node:{slug}:{control_id}".lower()


def _control_node(slug: str, c: dict, depth: int, parent: str | None, groups: dict[str, list[str]]) -> dict:
    notes = []
    if _prop(c, "crossmap-verified") == "false":
        notes.append("crossmap 미검증 항목")
    links = [l["href"] for l in c.get("links", [])]
    if links:
        notes.append("원문: " + " ".join(links))
    node = {
        "urn": node_urn(slug, c["id"]),
        "assessable": True,
        "depth": depth,
        "ref_id": _prop(c, "label") or c["id"],
        "name": c["title"],
    }
    if parent:
        node["parent_urn"] = parent
    statement = [p["prose"] for p in c.get("parts", []) if p.get("name") == "statement" and p.get("prose")]
    if statement:
        node["description"] = "\n".join(statement)
    if notes:
        node["annotation"] = "\n".join(notes)
    member = [g for g, ids in groups.items() if c["id"] in ids]
    if member:
        node["implementation_groups"] = member
    return node


def framework_library(slug: str, doc: dict, profiles: list[dict] | None = None) -> dict:
    """catalog 하나 → framework 라이브러리. profiles 는 이 catalog 를 import 하는 profile 들이다."""
    cat = doc["catalog"]
    md = cat["metadata"]
    groups: dict[str, list[str]] = {}
    group_defs = []
    for prof in profiles or []:
        pmd = prof["profile"]["metadata"]
        gid = _prop(pmd, "implementation-group")
        ids = [cid for inc in prof["profile"]["imports"][0]["include-controls"] for cid in inc["with-ids"]]
        groups[gid] = ids
        group_defs.append({"ref_id": gid, "name": pmd["title"].split(" — ")[-1],
                           "description": _prop(pmd, "basis") or ""})
    nodes = []

    def walk(node: dict, depth: int, parent: str | None) -> None:
        for g in node.get("groups", []):
            urn = node_urn(slug, g["id"])
            gn = {"urn": urn, "assessable": False, "depth": depth,
                  "ref_id": _prop(g, "label") or g["id"], "name": g["title"]}
            if parent:
                gn["parent_urn"] = parent
            nodes.append(gn)
            walk(g, depth + 1, urn)
        for c in node.get("controls", []):
            nodes.append(_control_node(slug, c, depth, parent, groups))

    walk(cat, 1, None)
    desc = [f"{k}: {v}" for k in ("source-kind", "source-version", "applies", "isms-version")
            if (v := _prop(md, k))]
    for k in ("crossmap-sha256", "source-sha256"):
        if v := _prop(md, k):
            desc.append(f"{k}: {v}")
    framework = {
        "urn": f"{URN}:framework:{slug}",
        "ref_id": slug,
        "name": md["title"],
        "description": "\n".join(desc),
        "requirement_nodes": nodes,
    }
    if group_defs:
        framework["implementation_groups_definition"] = group_defs
    return {
        "urn": f"{URN}:library:{slug}",
        "locale": "ko",
        "ref_id": slug,
        "name": md["title"],
        "description": "\n".join(desc),
        "version": _version(md),
        "publication_date": md["last-modified"][:10],
        "provider": PROVIDER,
        "packager": PACKAGER,
        "objects": {"framework": framework},
    }


def mapping_libraries(doc: dict, report: dict) -> dict[str, dict]:
    mc = doc["mapping-collection"]
    md = mc["metadata"]
    default_mr = mc["provenance"]["matching-rationale"]
    out = {}
    for m in mc["mappings"]:
        src = Path(m["source-resource"]["href"]).stem
        tgt = Path(m["target-resource"]["href"]).stem
        rows = []
        for mp in m["maps"]:
            rel = RELATIONSHIP_MAP.get(mp["relationship"])
            pairs = [(s["id-ref"], t["id-ref"]) for s in mp["sources"] for t in mp["targets"]]
            if rel is None:
                for s, t in pairs:
                    report["excluded"].append({
                        "source": f"{src}:{s}", "target": f"{tgt}:{t}",
                        "relationship": mp["relationship"],
                        "reason": "CISO Assistant 관계 값으로 옮기지 않는 값",
                    })
                continue
            for s, t in pairs:
                row = {
                    "source_requirement_urn": node_urn(src, s),
                    "target_requirement_urn": node_urn(tgt, t),
                    "relationship": rel,
                    "rationale": mp.get("matching-rationale", default_mr),
                }
                if mp.get("remarks"):
                    row["annotation"] = mp["remarks"]
                rows.append(row)
        if not rows:
            continue
        ref = f"mapping-{src}-and-{tgt}"
        out[ref] = {
            "urn": f"{URN}:library:{ref}",
            "locale": "ko",
            "ref_id": ref,
            "name": f"{src} <-> {tgt}",
            "description": f"{md['title']} ({md['version']})",
            "version": _version(md),
            "publication_date": md["last-modified"][:10],
            "provider": PROVIDER,
            "packager": PACKAGER,
            "dependencies": [f"{URN}:library:{src}", f"{URN}:library:{tgt}"],
            "objects": {
                "requirement_mapping_sets": [{
                    "urn": f"{URN}:req_mapping_set:{ref}",
                    "ref_id": ref,
                    "name": f"{src} <-> {tgt}",
                    "source_framework_urn": f"{URN}:framework:{src}",
                    "target_framework_urn": f"{URN}:framework:{tgt}",
                    "requirement_mappings": rows,
                }]
            },
        }
        report["mapped"] += len(rows)
    return out


def dump(obj: dict) -> str:
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, width=1000)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    try:
        outdir.prepare(out)
    except outdir.OutputDirError as e:
        print(f"출력 폴더 오류: {e}", file=sys.stderr)
        return 2
    report = {"mapped": 0, "excluded": []}
    n = 0
    profiles_by_catalog: dict[str, list[dict]] = {}
    for f in sorted((src / "profiles").glob("*.json")) if (src / "profiles").is_dir() else []:
        prof = json.loads(f.read_text(encoding="utf-8"))
        href = prof["profile"]["imports"][0]["href"]
        profiles_by_catalog.setdefault(Path(href).stem, []).append(prof)
    for f in sorted((src / "catalogs").glob("*.json")):
        lib = framework_library(f.stem, json.loads(f.read_text(encoding="utf-8")),
                                profiles_by_catalog.get(f.stem))
        (out / f"{f.stem}.yaml").write_text(dump(lib), encoding="utf-8")
        n += 1
    mpath = src / "mapping-collection.json"
    if mpath.exists():
        for ref, lib in mapping_libraries(json.loads(mpath.read_text(encoding="utf-8")), report).items():
            (out / f"{ref}.yaml").write_text(dump(lib), encoding="utf-8")
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"framework 라이브러리 {n}개, 매핑 행 {report['mapped']}건, 제외 {len(report['excluded'])}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
