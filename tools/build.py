#!/usr/bin/env python3
"""OSCAL 생성: ISMS-P 별표 catalog·profile + crossmap 법령 catalog·mapping-collection.

사용:
  python3 tools/build.py --crossmap <kr-compliance-ai>/data/crossmap.json --out build/oscal [--revision N]

출력 폴더는 비우고 다시 쓴다(tools/outdir.py). 결과:
  catalogs/<slug>.json, profiles/<slug>.json, mapping-collection.json(관계가 있을 때), report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import annex_to_oscal
import crossmap_to_oscal
import outdir
from oscal_common import dump

ROOT = Path(__file__).resolve().parent.parent
ISMS_SOURCE = ROOT / "sources" / "isms-p"
MAPPING_SOURCE_SLUG = "isms-p-2024-8-annex-7"


def build(crossmap_path: Path, out: Path, revision: int, sources: Path = ISMS_SOURCE) -> dict:
    if not (isinstance(revision, int) and 0 <= revision <= 99):
        raise crossmap_to_oscal.ConversionError("revision 은 0~99 정수여야 합니다.")
    catalogs, profiles, annex_report = annex_to_oscal.convert_all(sources, revision)
    raw = crossmap_path.read_bytes()
    law_catalogs, mapping, cm_report = crossmap_to_oscal.convert(
        json.loads(raw), hashlib.sha256(raw).hexdigest(), revision,
        MAPPING_SOURCE_SLUG, catalogs[MAPPING_SOURCE_SLUG])
    overlap = set(catalogs) & set(law_catalogs)
    if overlap:
        raise crossmap_to_oscal.ConversionError(f"catalog 이름이 겹칩니다: {sorted(overlap)}")
    outdir.prepare(out)
    (out / "catalogs").mkdir()
    (out / "profiles").mkdir()
    for slug, doc in {**catalogs, **law_catalogs}.items():
        (out / "catalogs" / f"{slug}.json").write_text(dump(doc), encoding="utf-8")
    for slug, doc in profiles.items():
        (out / "profiles" / f"{slug}.json").write_text(dump(doc), encoding="utf-8")
    if mapping:
        (out / "mapping-collection.json").write_text(dump(mapping), encoding="utf-8")
    report = {"annexes": annex_report, "crossmap": cm_report}
    (out / "report.json").write_text(dump(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--crossmap", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--revision", type=int, default=0,
                    help="같은 날짜 안에서 올리는 번호(0~99). 라이브러리 버전의 끝 두 자리가 된다.")
    a = ap.parse_args(argv)
    try:
        report = build(a.crossmap, a.out, a.revision)
    except (crossmap_to_oscal.ConversionError, annex_to_oscal.AnnexError, outdir.OutputDirError) as e:
        print(f"변환 실패: {e}", file=sys.stderr)
        return 2
    for slug, r in report["annexes"].items():
        print(f"{slug}: 영역별 항목 {r['counts']} (합계 {r['total']})")
    cm = report["crossmap"]
    print(f"crossmap: 매핑 {cm['mapped']}건, 관계 미정 {len(cm['unresolved'])}건, "
          f"ISMS-P 명칭 차이 {len(cm['isms_name_mismatch'])}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
