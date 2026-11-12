"""변환기 시험. 합성 fixture 만 쓴다."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import crossmap_to_oscal as c2o  # noqa: E402
import oscal_to_ciso as o2c  # noqa: E402
import validate_oscal as vo  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "crossmap-synthetic.json"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)


def tree_digest(path: Path) -> dict[str, str]:
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob("*")) if p.is_file()}


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def build(self, crossmap_path: Path, name: str) -> tuple[Path, Path]:
        oscal, ciso = self.tmp / f"{name}-oscal", self.tmp / f"{name}-ciso"
        r = run("tools/crossmap_to_oscal.py", str(crossmap_path), str(oscal))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("tools/oscal_to_ciso.py", str(oscal), str(ciso))
        self.assertEqual(r.returncode, 0, r.stderr)
        return oscal, ciso

    def test_deterministic(self):
        a = self.build(FIXTURE, "a")
        b = self.build(FIXTURE, "b")
        self.assertEqual(tree_digest(a[0]), tree_digest(b[0]))
        self.assertEqual(tree_digest(a[1]), tree_digest(b[1]))

    def test_schema_valid(self):
        oscal, _ = self.build(FIXTURE, "s")
        self.assertEqual(vo.validate_dir(oscal), [])

    def test_schema_rejects_bad_control_id(self):
        oscal, _ = self.build(FIXTURE, "bad")
        f = oscal / "catalogs" / "isms-p.json"
        doc = json.loads(f.read_text(encoding="utf-8"))
        doc["catalog"]["controls"][0]["id"] = "9.9.1"  # 숫자로 시작하는 ID 는 OSCAL token 이 아니다
        f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        errors = vo.validate_dir(oscal)
        self.assertTrue(any("isms-p.json" in e for e in errors), errors)

    def test_unresolved_link_is_not_mapped(self):
        oscal, _ = self.build(FIXTURE, "u")
        report = json.loads((oscal / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["unresolved"], ["9.9.1 → 신용정보법 제19조"])
        mc = json.loads((oscal / "mapping-collection.json").read_text(encoding="utf-8"))
        targets = {m["target-resource"]["href"] for m in mc["mapping-collection"]["mappings"]}
        self.assertNotIn("catalogs/credit-information-act.json", targets)
        # 관계가 없어도 조문은 catalog 에 남는다.
        self.assertTrue((oscal / "catalogs" / "credit-information-act.json").exists())

    def test_relationship_table_and_direction(self):
        _, ciso = self.build(FIXTURE, "r")
        rows = {}
        for f in ciso.glob("mapping-*.yaml"):
            lib = yaml.safe_load(f.read_text(encoding="utf-8"))
            ms = lib["objects"]["requirement_mapping_sets"][0]
            self.assertEqual(ms["source_framework_urn"], "urn:3iuy:risk:framework:isms-p")
            for r in ms["requirement_mappings"]:
                rows[(r["source_requirement_urn"], r["target_requirement_urn"])] = r
        n = "urn:3iuy:risk:req_node:"
        self.assertEqual(rows[(n + "isms-p:isms-p-9.9.1", n + "pipc-safety-measures:art-5")]["relationship"], "subset")
        self.assertEqual(rows[(n + "isms-p:isms-p-9.9.1", n + "pipa:art-29")]["relationship"], "intersect")
        self.assertEqual(rows[(n + "isms-p:isms-p-9.9.2", n + "pipc-safety-measures:art-15-2")]["relationship"], "superset")
        eq = rows[(n + "isms-p:isms-p-9.9.2", n + "electronic-financial-transactions-act:art-21")]
        self.assertEqual((eq["relationship"], eq["rationale"], eq["annotation"]), ("equal", "syntactic", "시험 근거 F"))
        self.assertEqual(len(rows), 4)

    def test_unsupported_relationships_reported(self):
        _, ciso = self.build(FIXTURE, "x")
        report = json.loads((ciso / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(e["relationship"] for e in report["excluded"]),
                         ["equivalent-to", "no-relationship"])

    def test_unverified_marked(self):
        oscal, ciso = self.build(FIXTURE, "v")
        cat = json.loads((oscal / "catalogs" / "isms-p.json").read_text(encoding="utf-8"))
        flags = {c["id"]: c2o_prop(c, "crossmap-verified") for c in cat["catalog"]["controls"]}
        self.assertEqual(flags, {"isms-p-9.9.1": "true", "isms-p-9.9.2": "false"})
        lib = yaml.safe_load((ciso / "isms-p.yaml").read_text(encoding="utf-8"))
        node = {n["ref_id"]: n for n in lib["objects"]["framework"]["requirement_nodes"]}
        self.assertIn("미검증", node["9.9.2"].get("annotation", ""))
        self.assertNotIn("annotation", node["9.9.1"])

    def test_rejects_unknown_source_and_bad_values(self):
        base = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cases = []
        d = copy.deepcopy(base); d["controls"][0]["law"][0]["name"] = "모르는법"; cases.append(d)
        d = copy.deepcopy(base); d["controls"][0]["law"][0]["relationship"] = "related"; cases.append(d)
        d = copy.deepcopy(base); d["controls"][0]["law"][0]["relationship_basis"] = ""; cases.append(d)
        d = copy.deepcopy(base); del d["_meta"]["mapping_method"]; cases.append(d)
        d = copy.deepcopy(base); d["controls"][1]["law"][0]["title"] = "다른 제목"; cases.append(d)
        for d in cases:
            with self.assertRaises(c2o.ConversionError):
                c2o.convert(d, "0" * 64)

    def test_no_relationships_means_no_mapping_file(self):
        d = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for c in d["controls"]:
            for ref in c.get("notice", []) + c.get("law", []):
                ref.pop("relationship", None)
        p = self.tmp / "empty.json"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        oscal, ciso = self.build(p, "e")
        self.assertFalse((oscal / "mapping-collection.json").exists())
        self.assertEqual(list(ciso.glob("mapping-*.yaml")), [])
        self.assertEqual(vo.validate_dir(oscal), [])

    def test_rerun_same_folder_drops_stale_outputs(self):
        oscal, ciso = self.tmp / "same-oscal", self.tmp / "same-ciso"
        for args in (("tools/crossmap_to_oscal.py", str(FIXTURE), str(oscal)),
                     ("tools/oscal_to_ciso.py", str(oscal), str(ciso))):
            self.assertEqual(run(*args).returncode, 0)
        self.assertTrue(list(ciso.glob("mapping-*.yaml")))
        # 관계를 모두 지우고, 전자금융거래법 연결도 지운 뒤 같은 폴더에 다시 변환한다.
        d = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for c in d["controls"]:
            c["law"] = [r for r in c["law"] if r["name"] != "전자금융거래법"]
            for ref in c.get("notice", []) + c.get("law", []):
                ref.pop("relationship", None)
        p = self.tmp / "reduced.json"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        for args in (("tools/crossmap_to_oscal.py", str(p), str(oscal)),
                     ("tools/oscal_to_ciso.py", str(oscal), str(ciso))):
            self.assertEqual(run(*args).returncode, 0)
        self.assertFalse((oscal / "mapping-collection.json").exists())
        self.assertFalse((oscal / "catalogs" / "electronic-financial-transactions-act.json").exists())
        self.assertEqual(list(ciso.glob("mapping-*.yaml")), [])
        self.assertFalse((ciso / "electronic-financial-transactions-act.yaml").exists())

    def test_refuses_foreign_nonempty_folder(self):
        out = self.tmp / "foreign"
        out.mkdir()
        (out / "keep.txt").write_text("x", encoding="utf-8")
        r = run("tools/crossmap_to_oscal.py", str(FIXTURE), str(out))
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((out / "keep.txt").exists())
        r = run("tools/oscal_to_ciso.py", str(self.tmp), str(out))
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((out / "keep.txt").exists())

    def test_revision_raises_library_version(self):
        def versions(rev):
            oscal, ciso = self.tmp / f"rev{rev}-oscal", self.tmp / f"rev{rev}-ciso"
            self.assertEqual(run("tools/crossmap_to_oscal.py", str(FIXTURE), str(oscal), "--revision", str(rev)).returncode, 0)
            self.assertEqual(run("tools/oscal_to_ciso.py", str(oscal), str(ciso)).returncode, 0)
            return {f.name: yaml.safe_load(f.read_text(encoding="utf-8"))["version"] for f in ciso.glob("*.yaml")}
        v0, v1 = versions(0), versions(1)
        self.assertEqual(set(v0.values()), {2026010200})
        self.assertEqual(set(v1.values()), {2026010201})
        with self.assertRaises(c2o.ConversionError):
            c2o.convert(json.loads(FIXTURE.read_text(encoding="utf-8")), "0" * 64, 100)


def c2o_prop(obj: dict, name: str) -> str | None:
    return o2c._prop(obj, name)


if __name__ == "__main__":
    unittest.main()
