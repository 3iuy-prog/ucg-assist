"""crossmap.json → OSCAL 법령·고시 catalog 와 mapping-collection.

입력은 law-assist(ai-a3sc)의 data/crossmap.json 이다. 변환은 코드만 한다(tools/build.py 가 부른다).
매핑의 source 는 ISMS-P 인증기준 별표 7 catalog(annex_to_oscal.py 가 만든다)의 control 이다.
관계 종류는 crossmap.json 에 사람이 적은 값만 쓰고, 비어 있으면 OSCAL 에 넣지 않고
보고서에 '관계 미정'으로 남긴다. 같은 입력이면 같은 출력이 나오도록 UUID 는 uuid5,
날짜는 crossmap.json 의 _meta.updated 로 정한다.
"""
from __future__ import annotations

from oscal_common import NS, metadata, prop, uid  # noqa: F401

RELATIONSHIPS = {
    "equivalent-to", "equal-to", "subset-of", "superset-of", "intersects-with", "no-relationship",
}
MATCHING_RATIONALES = {"syntactic", "semantic", "functional"}
METHODS = {"human", "automation", "hybrid"}
STATUSES = {"complete", "not-complete", "draft", "deprecated", "superseded"}

# crossmap.json 의 이름 → 카탈로그. 모르는 이름이 나오면 변환을 멈춘다(추측하지 않는다).
SOURCES = {
    ("L2", "안전성확보조치 기준"): {
        "slug": "pipc-safety-measures",
        "title": "개인정보의 안전성 확보조치 기준",
        "kind": "행정규칙·고시",
        "link": "https://www.law.go.kr/행정규칙/개인정보의안전성확보조치기준",
        "article_url": False,
    },
    ("L1", "개인정보보호법"): {
        "slug": "pipa",
        "title": "개인정보 보호법",
        "kind": "법령",
        "article_url": True,
        "link": "https://www.law.go.kr/법령/개인정보보호법",
    },
    ("L1", "신용정보법"): {
        "slug": "credit-information-act",
        "title": "신용정보의 이용 및 보호에 관한 법률",
        "kind": "법령",
        "article_url": True,
        "link": "https://www.law.go.kr/법령/신용정보의이용및보호에관한법률",
    },
    ("L1", "위치정보법"): {
        "slug": "location-information-act",
        "title": "위치정보의 보호 및 이용 등에 관한 법률",
        "kind": "법령",
        "article_url": True,
        "link": "https://www.law.go.kr/법령/위치정보의보호및이용등에관한법률",
    },
    ("L1", "전자금융거래법"): {
        "slug": "electronic-financial-transactions-act",
        "title": "전자금융거래법",
        "kind": "법령",
        "article_url": True,
        "link": "https://www.law.go.kr/법령/전자금융거래법",
    },
    ("L1", "정보통신망법"): {
        "slug": "network-act",
        "title": "정보통신망 이용촉진 및 정보보호 등에 관한 법률",
        "kind": "법령",
        "article_url": True,
        "link": "https://www.law.go.kr/법령/정보통신망이용촉진및정보보호등에관한법률",
    },
}


class ConversionError(Exception):
    pass


def article_id(article: str) -> str:
    # "제29조" → "art-29", "제15조의2" → "art-15-2"
    a = article.strip()
    if not (a.startswith("제") and "조" in a):
        raise ConversionError(f"조문 번호 형식을 알 수 없습니다: {article!r}")
    body = a[1:].replace("조의", "-").replace("조", "")
    if not body.replace("-", "").isdigit():
        raise ConversionError(f"조문 번호 형식을 알 수 없습니다: {article!r}")
    return f"art-{body}"


def convert(crossmap: dict, source_sha256: str, revision: int, isms_slug: str,
            isms_catalog: dict) -> tuple[dict[str, dict], dict | None, dict]:
    """crossmap 의 ISMS-P 항목은 isms_catalog(별표 7 catalog)의 control 을 가리킨다."""
    meta = crossmap.get("_meta", {})
    updated = meta.get("updated")
    if not updated or len(updated) != 10:
        raise ConversionError("_meta.updated(YYYY-MM-DD)가 필요합니다.")
    if not (isinstance(revision, int) and 0 <= revision <= 99):
        raise ConversionError("revision 은 0~99 정수여야 합니다.")
    # 같은 날 crossmap.json 을 고쳐 다시 올릴 때는 revision 을 올린다(CISO Assistant 는 버전이 커야 갱신한다).
    version = f"crossmap-{updated}-r{revision:02d}"
    src_props = [prop("crossmap-sha256", source_sha256)]

    isms_titles = {}
    for area in isms_catalog["catalog"]["groups"]:
        for field in area["groups"]:
            for c in field["controls"]:
                isms_titles[c["id"]] = c["title"]
    seen_isms: set[str] = set()
    target_controls: dict[str, dict[str, dict]] = {}
    maps_by_target: dict[str, list] = {}
    report = {"source_sha256": source_sha256, "unresolved": [], "mapped": 0, "isms_name_mismatch": []}

    for entry in crossmap.get("controls", []):
        isms = entry["isms"]
        sid = f"isms-p-{isms['id']}"
        if sid not in isms_titles:
            raise ConversionError(f"ISMS-P 항목이 별표 7 에 없습니다: {isms['id']}")
        if sid in seen_isms:
            raise ConversionError(f"ISMS-P 항목이 중복됩니다: {isms['id']}")
        seen_isms.add(sid)
        if isms.get("name") != isms_titles[sid]:
            report["isms_name_mismatch"].append(
                {"id": isms["id"], "crossmap": isms.get("name"), "annex": isms_titles[sid]})
        for group in ("notice", "law"):
            for ref in entry.get(group, []):
                key = (ref["layer"], ref["name"])
                if key not in SOURCES:
                    raise ConversionError(f"알 수 없는 근거 이름입니다: {ref['layer']} {ref['name']}")
                cat = SOURCES[key]
                tid = article_id(ref["article"])
                controls = target_controls.setdefault(cat["slug"], {})
                ctrl = {
                    "id": tid,
                    "title": ref["title"],
                    "props": [
                        {"name": "label", "value": ref["article"]},
                        prop("crossmap-verified", "true" if ref.get("verified") else "false"),
                    ],
                    "links": [{
                        "href": f"{cat['link']}/{ref['article']}" if cat["article_url"] else cat["link"],
                        "rel": "reference",
                    }],
                }
                prev = controls.get(tid)
                if prev and prev["title"] != ctrl["title"]:
                    raise ConversionError(f"같은 조문의 제목이 다릅니다: {ref['name']} {ref['article']}")
                if prev:
                    # 한 연결이라도 미검증이면 미검증으로 둔다.
                    if not ref.get("verified"):
                        prev["props"][1] = prop("crossmap-verified", "false")
                else:
                    controls[tid] = ctrl

                link_desc = f"{isms['id']} → {ref['name']} {ref['article']}"
                rel = ref.get("relationship")
                if not rel:
                    report["unresolved"].append(link_desc)
                    continue
                if rel not in RELATIONSHIPS:
                    raise ConversionError(f"허용하지 않는 relationship 값입니다: {rel!r} ({link_desc})")
                mr = ref.get("matching_rationale")
                if mr not in MATCHING_RATIONALES:
                    raise ConversionError(f"matching_rationale 이 없거나 허용하지 않는 값입니다: {mr!r} ({link_desc})")
                basis = (ref.get("relationship_basis") or "").strip()
                if not basis:
                    raise ConversionError(f"relationship_basis(판단 근거 문장)가 필요합니다: {link_desc}")
                m = {
                    "uuid": uid("map", isms_slug, sid, cat["slug"], tid),
                    "matching-rationale": mr,
                    "relationship": rel,
                    "sources": [{"type": "control", "id-ref": sid}],
                    "targets": [{"type": "control", "id-ref": tid}],
                    "props": [
                        prop("crossmap-isms-verified", "true" if isms.get("verified") else "false"),
                        prop("crossmap-target-verified", "true" if ref.get("verified") else "false"),
                    ],
                    "remarks": basis,
                }
                maps_by_target.setdefault(cat["slug"], []).append(m)
                report["mapped"] += 1

    catalogs: dict[str, dict] = {}
    for (layer, name), cat in sorted(SOURCES.items(), key=lambda kv: kv[1]["slug"]):
        controls = target_controls.get(cat["slug"])
        if not controls:
            continue
        extra = [prop("source-kind", cat["kind"])]
        if layer == "L2" and meta.get("notice_version"):
            extra.append(prop("source-version", meta["notice_version"]))
        else:
            extra.append(prop("source-version", "미기재"))
        catalogs[cat["slug"]] = {
            "catalog": {
                "uuid": uid("catalog", cat["slug"]),
                "metadata": metadata(cat["title"], updated, version, src_props + extra),
                "controls": sorted(controls.values(), key=lambda c: int(c["id"].split("-")[1])),
            }
        }

    mapping = None
    if maps_by_target:
        method = meta.get("mapping_method")
        status = meta.get("mapping_status")
        rationale = meta.get("mapping_matching_rationale")
        if method not in METHODS or status not in STATUSES or rationale not in MATCHING_RATIONALES:
            raise ConversionError(
                "관계가 하나라도 있으면 _meta.mapping_method·mapping_status·mapping_matching_rationale 이 필요합니다."
            )
        mappings = []
        for slug in sorted(maps_by_target):
            mappings.append({
                "uuid": uid("mapping", isms_slug, slug),
                "source-resource": {"type": "catalog", "href": f"catalogs/{isms_slug}.json"},
                "target-resource": {"type": "catalog", "href": f"catalogs/{slug}.json"},
                "maps": sorted(maps_by_target[slug], key=lambda m: (m["sources"][0]["id-ref"], m["targets"][0]["id-ref"])),
            })
        mapping = {
            "mapping-collection": {
                "uuid": uid("mapping-collection", "crossmap"),
                "metadata": metadata(meta.get("title", "crossmap"), updated, version, src_props),
                "provenance": {
                    "method": method,
                    "matching-rationale": rationale,
                    "status": status,
                    "mapping-description": meta.get("desc", ""),
                },
                "mappings": mappings,
            }
        }
    return catalogs, mapping, report
