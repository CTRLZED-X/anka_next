from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
M0 = ROOT / "reference" / "m0"
REUSE = M0 / "REUSE_MANIFEST_M0.json"
SPEC_ROOT = ROOT / "reference" / "master_specification" / "ANKA_NEXT_DEFINITIVE_BLUEPRINT"
Q0_RECEIPT = ROOT / "verification" / "Q0_baseline_receipt.json"

ALLOWED_EVIDENCE = {
    "ARCHIVED_RAW", "ARCHIVED_JOURNAL", "ARCHIVED_DIAGNOSTIC",
    "DERIVED", "SYNTHETIC", "MISSING",
}
ALLOWED_REUSE = {
    "UNCHANGED_REUSE", "ADAPTED_REUSE", "REIMPLEMENTED_FROM_BEHAVIOR",
    "HISTORICAL_FIXTURE_ONLY", "DISCARDED",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(obj: Any) -> str:
    data = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def common_zip_root(names: list[str]) -> str:
    first = [n.split("/", 1)[0] for n in names if "/" in n]
    if not first:
        return ""
    candidate = first[0]
    return candidate + "/" if all(n.startswith(candidate + "/") for n in names) else ""


def zip_file_map(path: Path) -> dict[str, tuple[str, int]]:
    with zipfile.ZipFile(path) as zf:
        names = [i.filename for i in zf.infolist() if not i.is_dir()]
        prefix = common_zip_root(names)
        result: dict[str, tuple[str, int]] = {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename[len(prefix):] if prefix and info.filename.startswith(prefix) else info.filename
            if not rel:
                continue
            h = hashlib.sha256()
            with zf.open(info, "r") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            if rel in result:
                raise ValueError(f"duplicate archive member after root normalization: {rel}")
            result[rel] = (h.hexdigest(), info.file_size)
        return result


def tree_digest(root: Path, *, exclude: set[str]) -> tuple[str, int, int]:
    rows=[]
    total=0
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        rel=p.relative_to(root).as_posix()
        if rel in exclude or rel.startswith(".pytest_cache/") or "/__pycache__/" in "/"+rel or rel.startswith("runtime/"):
            continue
        size=p.stat().st_size
        rows.append({"path":rel,"sha256":sha256_file(p),"bytes":size})
        total+=size
    return canonical_hash(rows), len(rows), total


class Gate:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, condition: bool, code: str, detail: str, **metrics: Any) -> None:
        row={"code":code,"status":"PASS" if condition else "FAIL","detail":detail}
        if metrics:
            row["metrics"]=metrics
        self.checks.append(row)

    @property
    def passed(self) -> bool:
        return all(c["status"] == "PASS" for c in self.checks)


def verify(args: argparse.Namespace) -> dict[str, Any]:
    started=time.time()
    g=Gate()

    baseline=load_json(M0/"baseline_sources.json")
    old_manifest=load_json(M0/"legacy_r5_198_file_manifest.json")
    p66_manifest=load_json(M0/"starting_p66_file_manifest.json")
    spec_manifest=load_json(M0/"master_specification_file_manifest.json")
    inventory=load_json(M0/"legacy_inventory.json")
    evidence=load_json(M0/"evidence_catalog.json")
    regressions=load_json(M0/"regression_catalog.json")
    pending=load_json(M0/"live_pending_boundaries.json")
    reuse=load_json(REUSE)

    # Frozen metadata file hashes.
    manifest_hash_ok=True
    for name, meta in baseline["manifests"].items():
        p = ROOT / name if name.startswith("provenance/") else M0 / name
        if not p.is_file() or sha256_file(p) != meta["sha256"] or p.stat().st_size != meta["bytes"]:
            manifest_hash_ok=False
            break
    g.check(manifest_hash_ok,"Q0-MANIFEST-HASHES","All M0 component manifests match the hashes frozen by baseline_sources.json.",count=len(baseline["manifests"]))

    # Exact immutable archives are bundled and hash-bound.
    archives_ok=True
    archive_details={}
    for key, meta in baseline["reference_archives"].items():
        bpath=meta.get("bundled_path") or meta.get("bundled_archive_path")
        p=ROOT/bpath if bpath else None
        ok=bool(p and p.is_file() and sha256_file(p)==meta["sha256"])
        archive_details[key]={"path":bpath,"sha256":meta["sha256"],"ok":ok}
        archives_ok &= ok
    g.check(archives_ok,"Q0-ARCHIVE-IDENTITY","Legacy R5.198, starting P66 and definitive specification archives are present byte-for-byte under reference/baselines.",archives=archive_details)

    # Each full file manifest is internally sealed and has unique valid entries.
    for code, manifest in [("LEGACY",old_manifest),("P66",p66_manifest),("SPEC",spec_manifest)]:
        files=manifest["files"]
        unique=len({r["path"] for r in files})==len(files)
        digest=canonical_hash(files)
        hashes_valid=all(len(r["sha256"])==64 and r["bytes"]>=0 for r in files)
        g.check(unique and hashes_valid and len(files)==manifest["file_count"] and digest==manifest["tree_digest_sha256"],
                f"Q0-{code}-FILE-MANIFEST",f"{code} complete file manifest is internally consistent and hash sealed.",file_count=len(files),tree_digest=digest)

    # Verify the exact bundled archive members against their manifests, not merely archive SHA.
    for code,key,manifest in [
        ("LEGACY","legacy_r5_198",old_manifest),
        ("P66","starting_anka_next_p66",p66_manifest),
        ("SPEC","definitive_master_specification",spec_manifest),
    ]:
        meta=baseline["reference_archives"][key]
        bpath=meta.get("bundled_path") or meta.get("bundled_archive_path")
        amap=zip_file_map(ROOT/bpath)
        expected={r["path"]:(r["sha256"],r["bytes"]) for r in manifest["files"]}
        g.check(amap==expected,f"Q0-{code}-ARCHIVE-CONTENTS",f"{code} archive members exactly match the frozen file manifest.",members=len(amap))

    # Authoritative specification is also extracted verbatim and readable in-tree.
    official=load_json(SPEC_ROOT/"SPECIFICATION_MANIFEST.json")
    extracted_ok=True
    for row in official["files"]:
        p=SPEC_ROOT/row["path"]
        if not p.is_file() or p.stat().st_size!=row["bytes"] or sha256_file(p)!=row["sha256"]:
            extracted_ok=False
            break
    extracted_ok &= official["reference_archive_sha256"] == baseline["reference_archives"]["legacy_r5_198"]["sha256"]
    g.check(extracted_ok,"Q0-SPEC-READABLE","Authoritative master-spec documents are extracted verbatim and their own manifest validates.",document_count=official["file_count"])

    # Q0 is a permanent baseline-integrity gate.  It verifies the frozen P66
    # starting archive rather than requiring the *current* runtime to remain P66
    # forever; later milestones are expected to change src/config under their own gates.
    p66_by_path={r["path"]:r for r in p66_manifest["files"]}
    frozen_p66=baseline["reference_archives"]["starting_anka_next_p66"]
    p66_archive=ROOT/(frozen_p66.get("bundled_path") or frozen_p66.get("bundled_archive_path"))
    frozen_ok=p66_archive.is_file() and sha256_file(p66_archive)==frozen_p66["sha256"]
    g.check(frozen_ok,"Q0-STARTING-P66-FROZEN","The exact immutable starting-P66 baseline remains present; current runtime evolution is verified by later milestone gates.",frozen_files=len(p66_by_path))
    g.check(not (ROOT/"src"/"anka_platform").exists(),"Q0-NO-LEGACY-RUNTIME","No legacy anka_platform package was copied into the new runtime import tree.")

    # Operator BAT surface remains exactly two files.
    bat_files=sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*.bat") if "reference/baselines/" not in p.relative_to(ROOT).as_posix())
    root_bats=sorted(p.name for p in ROOT.glob("*.bat") if p.is_file())
    allowed_internal={"tools/windows/_entry.bat"}
    internal_bats={x for x in bat_files if "/" in x}
    operator_surface_ok=root_bats==["setup.bat","start.bat"] and internal_bats.issubset(allowed_internal)
    g.check(operator_surface_ok,"Q0-OPERATOR-SURFACE","Only setup.bat and start.bat are user-facing at project root; the existing private Windows launcher helper remains internal.",root_bats=root_bats,internal_bats=sorted(internal_bats))

    # Reuse manifest integrity and current target hashes.
    old_by_path={r["path"]:r for r in old_manifest["files"]}
    p66_by_path={r["path"]:r for r in p66_manifest["files"]}
    reuse_ok=True
    unchanged_count=0
    for row in reuse["rows"]:
        if row["reuse_mode"] not in ALLOWED_REUSE or row["legacy_path"] not in old_by_path:
            reuse_ok=False; break
        if row["legacy_file_sha256"]!=old_by_path[row["legacy_path"]]["sha256"]:
            reuse_ok=False; break
        target=row.get("target_path")
        if target:
            p=ROOT/target
            if not p.is_file() or sha256_file(p)!=row.get("target_sha256"):
                reuse_ok=False; break
            if row["reuse_mode"]=="UNCHANGED_REUSE":
                unchanged_count += 1
                if row["legacy_file_sha256"] != row["target_sha256"]:
                    reuse_ok=False; break
        if not row.get("required_tests") or not row.get("rationale") or not row.get("known_limitations"):
            reuse_ok=False; break
    g.check(reuse_ok,"Q0-REUSE-MANIFEST","Reuse decisions are source-hash bound, mode constrained, scoped, limited and target-hash verified.",rows=len(reuse["rows"]),unchanged_rows=unchanged_count)

    # Evidence types and provenance path hashes.
    evidence_ok=set(evidence["allowed_classifications"])==ALLOWED_EVIDENCE
    missing_count=0
    for row in evidence["evidence"]:
        cls=row["classification"]
        if cls not in ALLOWED_EVIDENCE:
            evidence_ok=False; break
        if cls=="MISSING":
            missing_count += 1
            if row.get("path") or not row.get("limitation"):
                evidence_ok=False; break
            continue
        rel=row.get("path")
        if not rel or not row.get("sha256"):
            evidence_ok=False; break
        source_map = p66_by_path if row["source"]=="P66" else old_by_path if row["source"]=="R5.198" else None
        if source_map is None or rel not in source_map or source_map[rel]["sha256"]!=row["sha256"]:
            evidence_ok=False; break
    g.check(evidence_ok,"Q0-EVIDENCE-CATALOG","Evidence classes are explicit and provenance hashes resolve to the frozen source manifests; missing evidence remains explicit.",rows=len(evidence["evidence"]),missing=missing_count)

    # Historical regressions refer to real frozen source files; symptoms remain cause-neutral.
    regression_ok=True
    for row in regressions["regressions"]:
        doc=row["source_document"]
        if doc.startswith("master_specification/"):
            pass
        elif doc not in old_by_path:
            regression_ok=False; break
        if any(test not in old_by_path for test in row["legacy_test_paths"]):
            regression_ok=False; break
        if not row.get("permanent_invariant"):
            regression_ok=False; break
    g.check(regression_ok,"Q0-REGRESSION-CATALOG","Historical root-cause regressions and recurring symptom families are frozen without inventing single causes.",rows=len(regressions["regressions"]))

    # Pending live boundaries are explicit and cannot be accidentally marked accepted in M0.
    ids=[r["id"] for r in pending["items"]]
    pending_ok=len(ids)==len(set(ids)) and all(r["status"]=="BLOCKED_MISSING_EVIDENCE" and r["required_evidence"] for r in pending["items"])
    g.check(pending_ok,"Q0-LIVE-PENDING","Every M0 live/current-client boundary stays explicitly blocked pending named evidence.",items=len(ids))

    # Inventory must cover the mandatory M0 areas and be bound to exact R5.198 archive.
    required_areas={"game_kernel","game_data","calibration","protocol","tests","docs_and_handoffs","execution","coordination_workflow","observability_diagnostics_simulation"}
    inv_ok=inventory["reference_archive_sha256"]==baseline["reference_archives"]["legacy_r5_198"]["sha256"] and required_areas.issubset(inventory["areas"])
    g.check(inv_ok,"Q0-LEGACY-INVENTORY","Mandatory legacy Kernel/data/calibration/protocol/tests/docs and related reusable areas are inventoried.",areas=len(inventory["areas"]))

    source_digest,source_files,source_bytes=tree_digest(ROOT,exclude={Q0_RECEIPT.relative_to(ROOT).as_posix()})
    result={
        "schema_version":1,
        "gate":"Q0_BASELINE",
        "milestone":"M0",
        "status":"PASS" if g.passed else "FAIL",
        "source_tree_digest_sha256":source_digest,
        "source_tree_file_count":source_files,
        "source_tree_bytes":source_bytes,
        "baseline_archive_hashes":{k:v["sha256"] for k,v in baseline["reference_archives"].items()},
        "checks":g.checks,
        "summary":{
            "pass":sum(c["status"]=="PASS" for c in g.checks),
            "fail":sum(c["status"]=="FAIL" for c in g.checks),
            "physical_input_count":0,
            "live_client_contact":False,
            "known_live_blockers":len(pending["items"]),
        },
        "environment":{
            "python":platform.python_version(),
            "implementation":platform.python_implementation(),
            "platform":platform.platform(),
        },
        "duration_seconds":round(time.time()-started,6),
        "scope":"M0 provenance/baseline gate only. Does not certify current client, Windows behavior, protocol semantics, or physical input.",
    }
    return result


def main() -> int:
    ap=argparse.ArgumentParser(description="Verify ANKA_NEXT M0 immutable reference/evidence baseline.")
    ap.add_argument("--write-receipt", action="store_true", help="Write verification/Q0_baseline_receipt.json")
    ap.add_argument("--json", action="store_true", help="Print full JSON result")
    args=ap.parse_args()
    result=verify(args)
    if args.write_receipt:
        Q0_RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        Q0_RECEIPT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    if args.json:
        print(json.dumps(result,indent=2,ensure_ascii=False))
    else:
        print(f"Q0_BASELINE {result['status']} pass={result['summary']['pass']} fail={result['summary']['fail']} physical_input_count=0")
        for c in result["checks"]:
            print(f"[{c['status']}] {c['code']}: {c['detail']}")
    return 0 if result["status"]=="PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
