"""변환기 시험. crossmap 은 합성 데이터만 쓰고, ISMS-P 별표는 저장소의 고시 원문을 쓴다."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import annex_to_oscal as a2o  # noqa: E402
import build as builder  # noqa: E402
import crossmap_to_oscal as c2o  # noqa: E402
import oscal_to_ciso as o2c  # noqa: E402
import validate_oscal as vo  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "crossmap-synthetic.json"
SOURCES = ROOT / "sources" / "isms-p"
A7 = "isms-p-2024-8-annex-7"
A72 = "isms-p-2024-8-annex-7-2"
A73 = "isms-p-2024-8-annex-7-3"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)


def tree_digest(path: Path) -> dict[str, str]:
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(path.rglob("*")) if p.is_file()}


def load_yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def build(self, crossmap_path: Path, name: str, revision: int = 0) -> tuple[Path, Path]:
        oscal, ciso = self.tmp / f"{name}-oscal", self.tmp / f"{name}-ciso"
        r = run("tools/build.py", "--crossmap", str(crossmap_path), "--out", str(oscal), "--revision", str(revision))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("tools/oscal_to_ciso.py", str(oscal), str(ciso))
        self.assertEqual(r.returncode, 0, r.stderr)
        return oscal, ciso


class AnnexTest(Base):
    def test_counts_per_annex(self):
        _, _, report = a2o.convert_all(SOURCES, 0)
        self.assertEqual(report[A7]["counts"], {"1": 16, "2": 64, "3": 21})
        self.assertEqual(report[A72]["counts"], {"1": 8, "2": 33, "3": 21})
        self.assertEqual(report[A73]["counts"], {"1": 11, "2": 33, "3": 21})

    def test_profiles_follow_article_23(self):
        _, profiles, _ = a2o.convert_all(SOURCES, 0)

        def ids(key):
            return set(profiles[key]["profile"]["imports"][0]["include-controls"][0]["with-ids"])

        self.assertEqual(len(ids(f"{A7}-isms-p")), 101)
        self.assertEqual(len(ids(f"{A7}-isms")), 80)
        self.assertFalse(any(i.startswith("isms-p-3.") for i in ids(f"{A7}-isms")))
        # 제23조제3항제2호: 별표 7의2 가목(1.1.2. 항목 제외) 및 나목
        self.assertNotIn("isms-p-1.1.2", ids(f"{A72}-isms"))
        self.assertIn("isms-p-1.1.2", ids(f"{A72}-isms-p"))
        self.assertEqual(len(ids(f"{A72}-isms")), 8 - 1 + 33)
        # 제23조제4항에는 제외 항목이 없다.
        self.assertIn("isms-p-1.1.2", ids(f"{A73}-isms"))
        self.assertEqual(len(ids(f"{A73}-isms")), 11 + 33)

    def test_statement_text_kept(self):
        catalogs, _, _ = a2o.convert_all(SOURCES, 0)
        field = catalogs[A7]["catalog"]["groups"][1]["groups"][4]  # 2.5 인증 및 권한관리
        self.assertEqual(field["props"][0]["value"], "2.5")
        c = field["controls"][0]
        self.assertEqual((c["id"], c["title"]), ("isms-p-2.5.1", "사용자 계정 관리"))
        self.assertTrue(c["parts"][0]["prose"].startswith("정보시스템과 개인정보 및 중요정보에 대한 비인가 접근을 통제하고"))
        self.assertTrue(c["parts"][0]["prose"].endswith("보안책임이 있음을 규정화하고 인식시켜야 한다."))

    def test_parser_rejects_broken_tables(self):
        text = (SOURCES / "annex-7.txt").read_text(encoding="utf-8")
        cases = [
            text.replace("<td>1.1.2</td>", "<td>1.1.3</td>", 1),            # 번호 건너뜀
            text.replace("<td>최고책임자의 지정</td>", "<td></td>", 1),       # 빈 칸
            text.replace("나. 보호대책 요구사항", "다. 보호대책 요구사항", 1),  # 영역 순서
            text.replace("<td>2.1.</td>", "<td>1.9.</td>", 1),               # 분야가 영역과 다름
        ]
        for broken in cases:
            with self.assertRaises(a2o.AnnexError):
                a2o.parse_annex(broken)

    def test_source_hash_checked(self):
        src = self.tmp / "src"
        shutil.copytree(SOURCES, src)
        p = src / "annex-7.txt"
        p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaises(a2o.AnnexError):
            a2o.convert_all(src, 0)


class PipelineTest(Base):
    def test_deterministic(self):
        a = self.build(FIXTURE, "a")
        b = self.build(FIXTURE, "b")
        self.assertEqual(tree_digest(a[0]), tree_digest(b[0]))
        self.assertEqual(tree_digest(a[1]), tree_digest(b[1]))

    def test_schema_valid(self):
        oscal, _ = self.build(FIXTURE, "s")
        self.assertEqual(vo.validate_dir(oscal), [])

    def test_schema_rejects_bad_ids(self):
        oscal, _ = self.build(FIXTURE, "bad")
        f = oscal / "catalogs" / f"{A7}.json"
        doc = json.loads(f.read_text(encoding="utf-8"))
        doc["catalog"]["groups"][0]["groups"][0]["controls"][0]["id"] = "1.1.1"  # 숫자로 시작하면 OSCAL token 이 아니다
        f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        p = oscal / "profiles" / f"{A7}-isms.json"
        prof = json.loads(p.read_text(encoding="utf-8"))
        prof["profile"]["imports"][0]["include-controls"][0]["with-ids"].append("isms-p-9.9.9")
        p.write_text(json.dumps(prof, ensure_ascii=False), encoding="utf-8")
        errors = vo.validate_dir(oscal)
        self.assertTrue(any(e.startswith(f"{A7}.json") for e in errors), errors)
        self.assertTrue(any("isms-p-9.9.9" in e for e in errors), errors)

    def test_crossmap_targets_annex_7(self):
        oscal, _ = self.build(FIXTURE, "t")
        mc = json.loads((oscal / "mapping-collection.json").read_text(encoding="utf-8"))
        for m in mc["mapping-collection"]["mappings"]:
            self.assertEqual(m["source-resource"]["href"], f"catalogs/{A7}.json")
        report = json.loads((oscal / "report.json").read_text(encoding="utf-8"))["crossmap"]
        self.assertEqual(report["isms_name_mismatch"],
                         [{"id": "2.5.1", "crossmap": "시험 항목 하나", "annex": "사용자 계정 관리"}])
        d = json.loads(FIXTURE.read_text(encoding="utf-8"))
        d["controls"][0]["isms"]["id"] = "9.9.9"
        p = self.tmp / "missing.json"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        r = run("tools/build.py", "--crossmap", str(p), "--out", str(self.tmp / "missing"))
        self.assertNotEqual(r.returncode, 0)

    def test_unresolved_link_is_not_mapped(self):
        oscal, _ = self.build(FIXTURE, "u")
        report = json.loads((oscal / "report.json").read_text(encoding="utf-8"))["crossmap"]
        self.assertEqual(report["unresolved"], ["2.5.1 → 신용정보법 제19조"])
        mc = json.loads((oscal / "mapping-collection.json").read_text(encoding="utf-8"))
        targets = {m["target-resource"]["href"] for m in mc["mapping-collection"]["mappings"]}
        self.assertNotIn("catalogs/credit-information-act.json", targets)
        self.assertTrue((oscal / "catalogs" / "credit-information-act.json").exists())

    def test_relationship_table_and_direction(self):
        _, ciso = self.build(FIXTURE, "r")
        rows = {}
        for f in ciso.glob("mapping-*.yaml"):
            ms = load_yaml(f)["objects"]["requirement_mapping_sets"][0]
            self.assertEqual(ms["source_framework_urn"], f"urn:3iuy:risk:framework:{A7}")
            for r in ms["requirement_mappings"]:
                rows[(r["source_requirement_urn"], r["target_requirement_urn"])] = r
        n = "urn:3iuy:risk:req_node:"
        s1, s2 = f"{n}{A7}:isms-p-2.5.1", f"{n}{A7}:isms-p-2.5.5"
        self.assertEqual(rows[(s1, n + "pipc-safety-measures:art-5")]["relationship"], "subset")
        self.assertEqual(rows[(s1, n + "pipa:art-29")]["relationship"], "intersect")
        self.assertEqual(rows[(s2, n + "pipc-safety-measures:art-15-2")]["relationship"], "superset")
        eq = rows[(s2, n + "electronic-financial-transactions-act:art-21")]
        self.assertEqual((eq["relationship"], eq["rationale"], eq["annotation"]), ("equal", "syntactic", "시험 근거 F"))
        self.assertEqual(len(rows), 4)

    def test_unsupported_relationships_reported(self):
        _, ciso = self.build(FIXTURE, "x")
        report = json.loads((ciso / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(e["relationship"] for e in report["excluded"]),
                         ["equivalent-to", "no-relationship"])

    def test_crossmap_verified_flags_on_maps(self):
        oscal, ciso = self.build(FIXTURE, "v")
        mc = json.loads((oscal / "mapping-collection.json").read_text(encoding="utf-8"))
        flags = {}
        for m in mc["mapping-collection"]["mappings"]:
            for mp in m["maps"]:
                flags[mp["sources"][0]["id-ref"]] = o2c._prop(mp, "crossmap-isms-verified")
        self.assertEqual(flags, {"isms-p-2.5.1": "true", "isms-p-2.5.5": "false"})
        lib = load_yaml(ciso / "pipc-safety-measures.yaml")
        node = {n["ref_id"]: n for n in lib["objects"]["framework"]["requirement_nodes"]}
        self.assertIn("미검증", node["제15조의2"].get("annotation", ""))

    def test_ciso_hierarchy_and_groups(self):
        _, ciso = self.build(FIXTURE, "g")
        fw = load_yaml(ciso / f"{A72}.yaml")["objects"]["framework"]
        self.assertEqual({g["ref_id"] for g in fw["implementation_groups_definition"]}, {"ISMS", "ISMS-P"})
        nodes = {n["urn"].rsplit(":", 1)[1]: n for n in fw["requirement_nodes"]}
        self.assertFalse(nodes["area-1"]["assessable"])
        self.assertEqual(nodes["field-1.1"]["parent_urn"], f"urn:3iuy:risk:req_node:{A72}:area-1")
        c = nodes["isms-p-1.1.2"]
        self.assertEqual((c["assessable"], c["depth"], c["implementation_groups"]), (True, 3, ["ISMS-P"]))
        self.assertEqual(sorted(nodes["isms-p-1.1.1"]["implementation_groups"]), ["ISMS", "ISMS-P"])
        self.assertEqual(nodes["isms-p-3.1.1"]["implementation_groups"], ["ISMS-P"])
        assessable = [n for n in fw["requirement_nodes"] if n["assessable"]]
        self.assertEqual(len(assessable), 62)

    def test_rejects_unknown_source_and_bad_values(self):
        base = json.loads(FIXTURE.read_text(encoding="utf-8"))
        catalogs, _, _ = a2o.convert_all(SOURCES, 0)
        cases = []
        d = copy.deepcopy(base); d["controls"][0]["law"][0]["name"] = "모르는법"; cases.append(d)
        d = copy.deepcopy(base); d["controls"][0]["law"][0]["relationship"] = "related"; cases.append(d)
        d = copy.deepcopy(base); d["controls"][0]["law"][0]["relationship_basis"] = ""; cases.append(d)
        d = copy.deepcopy(base); del d["_meta"]["mapping_method"]; cases.append(d)
        d = copy.deepcopy(base); d["controls"][1]["law"][0]["title"] = "다른 제목"; cases.append(d)
        d = copy.deepcopy(base); d["controls"][1]["isms"]["id"] = "2.5.1"; cases.append(d)
        for d in cases:
            with self.assertRaises(c2o.ConversionError):
                c2o.convert(d, "0" * 64, 0, A7, catalogs[A7])

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
        for args in (("tools/build.py", "--crossmap", str(FIXTURE), "--out", str(oscal)),
                     ("tools/oscal_to_ciso.py", str(oscal), str(ciso))):
            self.assertEqual(run(*args).returncode, 0)
        self.assertTrue(list(ciso.glob("mapping-*.yaml")))
        d = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for c in d["controls"]:
            c["law"] = [r for r in c["law"] if r["name"] != "전자금융거래법"]
            for ref in c.get("notice", []) + c.get("law", []):
                ref.pop("relationship", None)
        p = self.tmp / "reduced.json"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        for args in (("tools/build.py", "--crossmap", str(p), "--out", str(oscal)),
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
        r = run("tools/build.py", "--crossmap", str(FIXTURE), "--out", str(out))
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((out / "keep.txt").exists())
        r = run("tools/oscal_to_ciso.py", str(self.tmp), str(out))
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((out / "keep.txt").exists())

    def test_revision_raises_library_version(self):
        def versions(rev):
            _, ciso = self.build(FIXTURE, f"rev{rev}", rev)
            return {f.stem: load_yaml(f)["version"] for f in ciso.glob("*.yaml")}
        v0, v1 = versions(0), versions(1)
        self.assertEqual(v0[A7], 2024072400)
        self.assertEqual(v1[A7], 2024072401)
        self.assertEqual(v0["pipa"], 2026010200)
        self.assertEqual(v1["pipa"], 2026010201)
        r = run("tools/build.py", "--crossmap", str(FIXTURE), "--out", str(self.tmp / "r100"), "--revision", "100")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
