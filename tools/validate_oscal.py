#!/usr/bin/env python3
"""생성한 OSCAL 파일을 고정한 NIST OSCAL 1.2.3 JSON 스키마로 검사한다.

스키마 파일은 schemas/oscal-1.2.3/ 에 있고, SHA-256 이 SCHEMA_SHA256 과 다르면 검사하지 않는다.
NIST 스키마의 정규식은 \\p{L}·\\p{N}(유니코드 문자 범주)을 쓰는데 파이썬 re 는 이를 지원하지 않는다.
그래서 검사 전에 \\p{L} 을 [^\\W\\d_](유니코드 글자), \\p{N} 을 \\d(유니코드 숫자)로 바꾼다.
\\d 는 Nd 범주만 맞추므로 \\p{N} 보다 좁다(검사가 더 엄격해지는 쪽).

또 OSCAL 스키마가 표현하지 못하는 제약(map 의 relationship 허용값, mapping 이 가리키는
catalog 파일·control ID 존재)을 추가로 검사한다.

사용:
  python3 tools/validate_oscal.py <출력 폴더>
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from jsonschema import Draft7Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas" / "oscal-1.2.3"
SCHEMA_SHA256 = {
    "oscal_catalog_schema.json": "ab95836e9e8dfeb6fde80007f6cc76fa3192f595d427c751a3f3923c3f474fc2",
    "oscal_mapping_schema.json": "ed28b68c8e56cc7d39f0c6076a5d7da3e8100fbe25abf5bb731120bd34f8817e",
}
RELATIONSHIPS = {
    "equivalent-to", "equal-to", "subset-of", "superset-of", "intersects-with", "no-relationship",
}


def load_schema(name: str) -> dict:
    raw = (SCHEMA_DIR / name).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SCHEMA_SHA256[name]:
        raise SystemExit(f"스키마 해시가 다릅니다: {name} {digest}")
    text = raw.decode("utf-8").replace("\\\\p{L}", "[^\\\\W\\\\d_]").replace("\\\\p{N}", "\\\\d")
    return json.loads(text)


def schema_errors(doc: dict, schema: dict) -> list[str]:
    v = Draft7Validator(schema, format_checker=FormatChecker())
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in v.iter_errors(doc)]


def validate_dir(out: Path) -> list[str]:
    errors: list[str] = []
    cat_schema = load_schema("oscal_catalog_schema.json")
    map_schema = load_schema("oscal_mapping_schema.json")
    control_ids: dict[str, set[str]] = {}
    for f in sorted((out / "catalogs").glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        errors += [f"{f.name}: {e}" for e in schema_errors(doc, cat_schema)]
        control_ids[f"catalogs/{f.name}"] = {c["id"] for c in doc["catalog"].get("controls", [])}
    mpath = out / "mapping-collection.json"
    if mpath.exists():
        doc = json.loads(mpath.read_text(encoding="utf-8"))
        errors += [f"{mpath.name}: {e}" for e in schema_errors(doc, map_schema)]
        for m in doc["mapping-collection"]["mappings"]:
            src = m["source-resource"]["href"]
            tgt = m["target-resource"]["href"]
            for href in (src, tgt):
                if href not in control_ids:
                    errors.append(f"{mpath.name}: 가리키는 catalog 가 없습니다: {href}")
            for mp in m["maps"]:
                if mp["relationship"] not in RELATIONSHIPS:
                    errors.append(f"{mpath.name}: relationship 값이 허용 목록에 없습니다: {mp['relationship']}")
                for side, href in (("sources", src), ("targets", tgt)):
                    for item in mp[side]:
                        if item["id-ref"] not in control_ids.get(href, set()):
                            errors.append(f"{mpath.name}: {href} 에 없는 control 입니다: {item['id-ref']}")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    errors = validate_dir(Path(sys.argv[1]))
    for e in errors:
        print(e)
    print("검사 통과" if not errors else f"오류 {len(errors)}건")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
