"""ISMS-P 인증기준 별표 원문 → OSCAL catalog·profile.

sources/isms-p/manifest.json 에 적힌 별표 파일(법제처 API 로 받은 텍스트)을 읽어
영역(가·나·다목) > 분야 > 항목 구조의 OSCAL catalog 를 만든다. 고시 제23조의 인증 구분
(ISMS·ISMS-P)은 별표마다 OSCAL profile 로 만든다. profile 은 include-controls 의
with-ids 만 쓴다(import 하나, merge·modify 없음).

파싱 검사: 영역 표제가 가·나·다 순서인지, 항목 ID 가 분야 ID 로 시작하는지,
분야 안에서 항목 번호가 1부터 빠짐없이 이어지는지, 항목 ID 가 중복되지 않는지,
빈 칸이 없는지. manifest 에 영역별 기대 개수가 있으면 그 값과도 대조한다.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from oscal_common import NS, metadata, prop, uid

AREA_RE = re.compile(r"^([가나다])\.\s+(.+)$")
ROW_RE = re.compile(r"^<tr>((?:<td>.*?</td>){5})</tr>$")
CELL_RE = re.compile(r"<td>(.*?)</td>")
AREA_NO = {"가": "1", "나": "2", "다": "3"}


class AnnexError(Exception):
    pass


def control_id(ref: str) -> str:
    return f"isms-p-{ref}"


def parse_annex(text: str) -> list[dict]:
    areas: list[dict] = []
    field = None
    seen: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        m = AREA_RE.match(line)
        if m:
            letter, title = m.groups()
            expected = "가나다"[len(areas)] if len(areas) < 3 else None
            if letter != expected:
                raise AnnexError(f"{lineno}행: 영역 표제 순서가 맞지 않습니다: {line}")
            areas.append({"no": AREA_NO[letter], "letter": letter, "title": title.strip(), "fields": []})
            field = None
            continue
        if not line.startswith("<tr><td>"):
            continue
        m = ROW_RE.match(line)
        if not m:
            raise AnnexError(f"{lineno}행: 표 행 형식을 알 수 없습니다: {line[:80]}")
        if not areas:
            raise AnnexError(f"{lineno}행: 영역 표제 전에 표 행이 있습니다.")
        f_id, f_name, ref, title, body = [c.strip() for c in CELL_RE.findall(m.group(1))]
        area = areas[-1]
        if f_id:
            f_ref = f_id.rstrip(".")
            if not f_ref.startswith(area["no"] + ".") or not f_name:
                raise AnnexError(f"{lineno}행: 분야가 영역과 맞지 않습니다: {f_id} {f_name}")
            field = {"ref": f_ref, "title": f_name, "controls": []}
            area["fields"].append(field)
        elif f_name:
            raise AnnexError(f"{lineno}행: 분야 번호 없이 분야 이름만 있습니다: {f_name}")
        if field is None:
            raise AnnexError(f"{lineno}행: 분야가 정해지기 전에 항목이 있습니다.")
        if not (ref and title and body):
            raise AnnexError(f"{lineno}행: 빈 칸이 있습니다: {ref!r} {title!r}")
        expected_ref = f"{field['ref']}.{len(field['controls']) + 1}"
        if ref != expected_ref:
            raise AnnexError(f"{lineno}행: 항목 번호가 {expected_ref} 이어야 하는데 {ref} 입니다.")
        if ref in seen:
            raise AnnexError(f"{lineno}행: 항목 번호가 중복됩니다: {ref}")
        seen.add(ref)
        field["controls"].append({"ref": ref, "title": title, "statement": body})
    if [a["letter"] for a in areas] != ["가", "나", "다"]:
        raise AnnexError("가·나·다목이 모두 있어야 합니다.")
    return areas


def counts(areas: list[dict]) -> dict[str, int]:
    return {a["no"]: sum(len(f["controls"]) for f in a["fields"]) for a in areas}


def build_catalog(spec: dict, notice: dict, areas: list[dict], version: str, source_sha256: str) -> dict:
    groups = []
    for a in areas:
        fields = []
        for f in a["fields"]:
            controls = [{
                "id": control_id(c["ref"]),
                "title": c["title"],
                "props": [{"name": "label", "value": c["ref"]}],
                "parts": [{
                    "id": control_id(c["ref"]) + "_smt",
                    "name": "statement",
                    "prose": c["statement"],
                }],
            } for c in f["controls"]]
            fields.append({
                "id": f"field-{f['ref']}",
                "title": f["title"],
                "props": [{"name": "label", "value": f["ref"]}],
                "controls": controls,
            })
        groups.append({
            "id": f"area-{a['no']}",
            "title": a["title"],
            "props": [{"name": "label", "value": f"{a['letter']}목"}],
            "groups": fields,
        })
    md = metadata(spec["title"], notice["effective"], version, [
        prop("source-kind", "행정규칙·고시"),
        prop("source-version", f"{notice['title']} {notice['number']} ({notice['effective']} 시행)"),
        prop("source-annex", spec["file"]),
        prop("source-sha256", source_sha256),
        prop("applies", spec["applies"]),
    ])
    md["links"] = [{"href": notice["url"], "rel": "source"}]
    return {"catalog": {"uuid": uid("catalog", spec["slug"]), "metadata": md, "groups": groups}}


def profile_ids(areas: list[dict], rule: dict) -> list[str]:
    ids = [c["ref"] for a in areas if a["no"] in rule["areas"] for f in a["fields"] for c in f["controls"]]
    for ex in rule["exclude"]:
        if ex not in ids:
            raise AnnexError(f"제외할 항목이 별표에 없습니다: {ex}")
    return [control_id(r) for r in ids if r not in rule["exclude"]]


def build_profile(spec: dict, notice: dict, areas: list[dict], rule: dict, version: str) -> dict:
    md = metadata(f"{spec['title']} — {rule['name']}", notice["effective"], version, [
        prop("implementation-group", rule["group"]),
        prop("basis", rule["basis"]),
    ])
    return {"profile": {
        "uuid": uid("profile", spec["slug"], rule["group"]),
        "metadata": md,
        "imports": [{
            "href": f"../catalogs/{spec['slug']}.json",
            "include-controls": [{"with-ids": profile_ids(areas, rule)}],
        }],
    }}


def convert_all(source_dir: Path, revision: int) -> tuple[dict[str, dict], dict[str, dict], dict]:
    import json
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    notice = manifest["notice"]
    version = f"notice-{notice['effective']}-r{revision:02d}"
    catalogs, profiles, report = {}, {}, {}
    for spec in manifest["annexes"]:
        raw = (source_dir / spec["file"]).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != manifest["files"][spec["file"]]["sha256"]:
            raise AnnexError(f"원문 파일 해시가 manifest 와 다릅니다: {spec['file']}")
        areas = parse_annex(raw.decode("utf-8"))
        got = counts(areas)
        if spec.get("expected_counts") and got != spec["expected_counts"]:
            raise AnnexError(f"{spec['file']} 영역별 항목 수 {got} 가 기대값 {spec['expected_counts']} 와 다릅니다.")
        catalogs[spec["slug"]] = build_catalog(spec, notice, areas, version, digest)
        for rule in spec["profiles"]:
            profiles[f"{spec['slug']}-{rule['group'].lower()}"] = build_profile(spec, notice, areas, rule, version)
        report[spec["slug"]] = {"counts": got, "total": sum(got.values())}
    return catalogs, profiles, report


__all__ = ["AnnexError", "parse_annex", "convert_all", "control_id", "NS"]
