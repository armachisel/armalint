"""Aggregate test runner for Armalint (standard library only).

Runs each analyzer module's self-test in a subprocess, then exercises the CLI
against the fixture files. Exits non-zero if any step fails.

Usage (from the project root)::

    python tests/run_all.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from armalint.linter import lint_text
from analysis_cases import CASES as ANALYSIS_CASES
from corpus_runner import run_corpus

TESTS_DIR = PROJECT_ROOT / "tests"
FIXTURES_DIR = TESTS_DIR / "fixtures"

# Analyzer modules with a ``if __name__ == "__main__":`` self-test.
SELF_TEST_MODULES = (
    "tokenizer",
    "ast",
    "control_flow",
    "definitions",
    "syntax",
    "argument_types",
    "undefined",
    "functions",
    "known",
    "commands",
    "rapified",
    "cfgfunctions",
    "config_lint",
    "locals",
)

CLEAN_FIXTURE = FIXTURES_DIR / "clean.sqf"
BUGGY_FIXTURE = FIXTURES_DIR / "buggy.sqf"
MISSION_FIXTURE = FIXTURES_DIR / "mission"
MODFUNCS_FIXTURE = FIXTURES_DIR / "modfuncs"
INCLUDE_FIXTURE = FIXTURES_DIR / "include"
PARAMS_FIXTURE = FIXTURES_DIR / "params.sqf"
CALL_TARGETS_FIXTURE = FIXTURES_DIR / "call_targets.sqf"
MULTILINE_FIXTURE = FIXTURES_DIR / "multiline.sqf"
UNKNOWN_COMMAND_FIXTURE = FIXTURES_DIR / "unknown_command.sqf"
MODCACHE_FIXTURE = FIXTURES_DIR / "modcache"
CONFIG_CODE_FIXTURE = FIXTURES_DIR / "config_code"

# Codes that must appear in the JSON output when linting the buggy fixture.
EXPECTED_BUGGY_CODES = ("E001", "W101", "W201")


def run_module_selftest(name: str, *extra: str) -> tuple[bool, str]:
    """Run ``python -m armalint.<name> [extra...]``; return ``(passed, output)``."""
    proc = subprocess.run(
        [sys.executable, "-m", f"armalint.{name}", *extra],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI in a subprocess from the project root."""
    return subprocess.run(
        [sys.executable, "-m", "armalint", *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )


def main() -> int:
    failures: list[str] = []
    passed = 0
    total = 0

    print(f"project root : {PROJECT_ROOT}")
    print("--- module self-tests ---")

    print("--- counted parser/analysis cases ---")
    for name, case in ANALYSIS_CASES:
        total += 1
        try:
            ok = bool(case())
        except Exception as exc:
            ok = False
            failures.append(f"analysis case {name} raised {exc!r}")
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if ok:
            passed += 1
        elif not any(f"analysis case {name}" in item for item in failures):
            failures.append(f"analysis case failed: {name}")

    total += 1
    type_diags = lint_text(
        'hint 42; sleep 1; [42] call acme_fnc_route;',
        function_signatures={"acme_fnc_route": ["Object"]},
    )
    type_codes = [d.code for d in type_diags]
    type_ok = type_codes.count("W203") == 2
    print(f"[{'PASS' if type_ok else 'FAIL'}] linter integrates built-in and configured mod-function type checks")
    if type_ok:
        passed += 1
    else:
        failures.append(f"expected one W203 from lint_text, got {type_diags!r}")

    total += 1
    with tempfile.TemporaryDirectory() as temp_dir:
        mission_file = Path(temp_dir) / "typed_mod_call.sqf"
        mission_file.write_text("[42] call acme_fnc_route;\n", encoding="utf-8")
        (Path(temp_dir) / "armalint_mods.json").write_text(
            '["acme_fnc_route"]', encoding="utf-8"
        )
        (Path(temp_dir) / "armalint_mods_types.json").write_text(
            '{"acme_fnc_route": ["Object"]}', encoding="utf-8"
        )
        proc = run_cli(str(mission_file), "--json")
    try:
        type_payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        type_payload = []
    mod_type_ok = proc.returncode == 0 and any(d.get("code") == "W203" for d in type_payload) and not any(d.get("code") == "W201" for d in type_payload)
    print(f"[{'PASS' if mod_type_ok else 'FAIL'}] CLI loads extracted mod function types")
    if mod_type_ok:
        passed += 1
    else:
        failures.append(f"expected cache-backed W203 without W201, got {type_payload!r}")

    for name in SELF_TEST_MODULES:
        total += 1
        ok, output = run_module_selftest(name)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] armalint.{name}")
        if output:
            for line in output.splitlines():
                print(f"         {line}")
        if ok:
            passed += 1
        else:
            failures.append(f"module self-test failed: armalint.{name}")

    total += 1
    try:
        from armalint.rule_docs import render_rule_catalog
        generated_catalog = (PROJECT_ROOT / "docs" / "rule-catalog.md").read_text(encoding="utf-8")
        docs_ok = generated_catalog == render_rule_catalog()
    except OSError:
        docs_ok = False
    print(f"[{'PASS' if docs_ok else 'FAIL'}] generated rule catalog is current")
    if docs_ok:
        passed += 1
    else:
        failures.append("generated rule catalog is stale")

    total += 1
    corpus_passed, corpus_total, corpus_failures = run_corpus()
    corpus_ok = corpus_passed == corpus_total
    print(f"[{'PASS' if corpus_ok else 'FAIL'}] regression corpus {corpus_passed}/{corpus_total}")
    if corpus_ok:
        passed += 1
    else:
        failures.extend(f"corpus: {failure}" for failure in corpus_failures)

    print("--- module self-tests (with flags) ---")
    for name, extra in (("update", ("--self-test",)),):
        total += 1
        ok, output = run_module_selftest(name, *extra)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] armalint.{name} {' '.join(extra)}")
        if output:
            for line in output.splitlines():
                print(f"         {line}")
        if ok:
            passed += 1
        else:
            failures.append(f"module self-test failed: armalint.{name} {' '.join(extra)}")

    print("--- CLI: clean fixture (expect exit 0, 0 diagnostics) ---")
    total += 1
    clean = run_cli(str(CLEAN_FIXTURE))
    clean_ok = clean.returncode == 0
    print(f"[{'PASS' if clean_ok else 'FAIL'}] clean.sqf exit={clean.returncode}")
    if clean.stdout.strip():
        for line in clean.stdout.strip().splitlines():
            print(f"         {line}")
    if clean_ok:
        passed += 1
    else:
        failures.append("clean.sqf: expected exit 0")
    if "0 diagnostic" not in clean.stdout:
        failures.append("clean.sqf: expected 0 diagnostics in output")

    print("--- CLI: multiline fixture (expect exit 0, 0 diagnostics) ---")
    total += 1
    multiline = run_cli(str(MULTILINE_FIXTURE), "--json")
    multiline_payload = []
    if multiline.stdout.strip():
        try:
            multiline_payload = json.loads(multiline.stdout)
        except json.JSONDecodeError:
            multiline_payload = []
    multiline_ok = multiline.returncode == 0 and len(multiline_payload) == 0
    print(f"[{'PASS' if multiline_ok else 'FAIL'}] multiline.sqf exit={multiline.returncode} diagnostics={len(multiline_payload)}")
    if multiline_payload:
        for line in json.dumps(multiline_payload, indent=2).splitlines():
            print(f"         {line}")
    if multiline_ok:
        passed += 1
    else:
        if multiline.returncode != 0:
            failures.append("multiline.sqf: expected exit 0")
        if len(multiline_payload) != 0:
            failures.append(f"multiline.sqf: expected 0 diagnostics, got {len(multiline_payload)}")

    print("--- CLI: buggy fixture (expect exit 1 + E001/W101/W201) ---")
    total += 1
    buggy = run_cli(str(BUGGY_FIXTURE))
    buggy_exit_ok = buggy.returncode == 1

    buggy_json = run_cli(str(BUGGY_FIXTURE), "--json")
    buggy_codes: set[str] = set()
    if buggy_json.stdout.strip():
        try:
            payload = json.loads(buggy_json.stdout)
            buggy_codes = {str(d.get("code", "")) for d in payload}
        except json.JSONDecodeError:
            buggy_codes = set()
    missing = [c for c in EXPECTED_BUGGY_CODES if c not in buggy_codes]

    buggy_ok = buggy_exit_ok and not missing
    print(f"[{'PASS' if buggy_ok else 'FAIL'}] buggy.sqf exit={buggy.returncode} codes={sorted(buggy_codes) or '[]'}")
    if buggy.stdout.strip():
        for line in buggy.stdout.strip().splitlines():
            print(f"         {line}")
    if buggy_ok:
        passed += 1
    else:
        if not buggy_exit_ok:
            failures.append("buggy.sqf: expected exit 1")
        if missing:
            failures.append(f"buggy.sqf: missing expected codes {missing} in JSON output")

    print("--- CLI: SARIF fingerprints and JSON baseline ---")
    total += 1
    sarif_proc = run_cli(str(BUGGY_FIXTURE), "--sarif")
    try:
        sarif_payload = json.loads(sarif_proc.stdout)
        sarif_run = sarif_payload["runs"][0]
        sarif_results = sarif_run["results"]
        sarif_ok = (
            sarif_proc.returncode == 1
            and sarif_payload.get("version") == "2.1.0"
            and sarif_run.get("automationDetails", {}).get("id") == "armalint/default"
            and bool(sarif_results)
            and all(result.get("partialFingerprints", {}).get("armalint/v1") for result in sarif_results)
            and all("helpUri" in rule for rule in sarif_run["tool"]["driver"].get("rules", []))
            and all(result.get("level") in {"error", "warning", "note"} for result in sarif_results)
        )
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        sarif_ok = False
        sarif_results = []
    baseline_ok = False
    if buggy_json.stdout.strip():
        try:
            baseline_entry = json.loads(buggy_json.stdout)[0]
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as baseline_file:
                json.dump({"diagnostics": [baseline_entry]}, baseline_file)
                baseline_path = baseline_file.name
            baseline_proc = run_cli(str(BUGGY_FIXTURE), "--baseline", baseline_path, "--json")
            baseline_payload = json.loads(baseline_proc.stdout or "[]")
            baseline_ok = len(baseline_payload) == max(0, len(json.loads(buggy_json.stdout)) - 1)
            Path(baseline_path).unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError, IndexError, TypeError):
            baseline_ok = False
    sarif_baseline_ok = sarif_ok and baseline_ok
    print(f"[{'PASS' if sarif_baseline_ok else 'FAIL'}] SARIF results={len(sarif_results)} baseline={baseline_ok}")
    if sarif_baseline_ok:
        passed += 1
    else:
        failures.append("SARIF or baseline integration did not produce stable CI metadata")

    print("--- include provenance, watcher, and LSP smoke tests ---")
    total += 1
    provenance_ok = watcher_ok = lsp_ok = False
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        shared = temp_root / "shared.sqf"
        main_file = temp_root / "main.sqf"
        shared.write_text("hint str _missing;\n", encoding="utf-8")
        main_file.write_text('#include "shared.sqf"\n', encoding="utf-8")
        related_proc = run_cli(str(main_file), "--sarif")
        try:
            related_results = json.loads(related_proc.stdout)["runs"][0]["results"]
            provenance_ok = any(result.get("relatedLocations") for result in related_results)
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            provenance_ok = False
        try:
            from armalint.watch import IncrementalLinter
            watcher = IncrementalLinter([str(temp_root)])
            first_events = watcher.poll()
            second_events = watcher.poll()
            watcher_ok = bool(first_events) and not second_events
        except Exception:
            watcher_ok = False
        try:
            from armalint.lsp import Server
            server = Server()
            server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            _response, notifications = server.handle({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {"uri": main_file.as_uri(), "text": "hint str _missing;"}}})
            lsp_ok = bool(notifications and notifications[0]["method"] == "textDocument/publishDiagnostics")
        except Exception:
            lsp_ok = False
    tooling_ok = provenance_ok and watcher_ok and lsp_ok
    print(f"[{'PASS' if tooling_ok else 'FAIL'}] related={provenance_ok} watcher={watcher_ok} lsp={lsp_ok}")
    if tooling_ok:
        passed += 1
    else:
        failures.append("include provenance, watcher, or LSP smoke test failed")

    print("--- CLI: safe fixes, severity threshold, and GitHub annotations ---")
    total += 1
    with tempfile.TemporaryDirectory() as temp_dir:
        style_file = Path(temp_dir) / "style.sqf"
        style_file.write_text('hint "x";  \n\thint "y";\n', encoding="utf-8")
        preview = run_cli(str(style_file), "--fix-preview")
        preview_payload = json.loads(preview.stdout or "[]")
        preview_ok = preview.returncode == 0 and preview_payload and "edits" in preview_payload[0] and "  \n" in style_file.read_text(encoding="utf-8")
        fixed = run_cli(str(style_file), "--fix", "--style", "--json")
        fixed_payload = json.loads(fixed.stdout or "[]")
        fix_ok = fixed.returncode == 0 and not fixed_payload and "  \n" not in style_file.read_text(encoding="utf-8") and "\t" not in style_file.read_text(encoding="utf-8")
    warning_fail = run_cli(str(BUGGY_FIXTURE), "--fail-on", "warning").returncode == 1
    no_fail = run_cli(str(BUGGY_FIXTURE), "--fail-on", "none").returncode == 0
    diff_clean = run_cli(str(BUGGY_FIXTURE), "--diff", "HEAD", "--json")
    diff_ok = diff_clean.returncode == 0 and json.loads(diff_clean.stdout or "[]") == []
    annotation = run_cli(str(BUGGY_FIXTURE), "--github-actions")
    annotation_ok = "::error" in annotation.stdout and "::warning" in annotation.stdout
    checkstyle = run_cli(str(BUGGY_FIXTURE), "--checkstyle")
    checkstyle_ok = checkstyle.returncode == 1 and "<checkstyle" in checkstyle.stdout and "<error" in checkstyle.stdout
    timings = run_cli(str(CLEAN_FIXTURE), "--timings", "--json")
    try:
        timing_payload = json.loads(timings.stderr or "{}")
        timings_ok = timings.returncode == 0 and "total_ms" in timing_payload and "lint_ms" in timing_payload
    except json.JSONDecodeError:
        timings_ok = False
    limited = run_cli(str(BUGGY_FIXTURE), "--max-issues", "1", "--json")
    try:
        limited_payload = json.loads(limited.stdout or "[]")
        max_issues_ok = limited.returncode == 1 and len(limited_payload) == 1
    except json.JSONDecodeError:
        max_issues_ok = False
    policy_ok = preview_ok and fix_ok and warning_fail and no_fail and diff_ok and annotation_ok and checkstyle_ok and timings_ok and max_issues_ok
    print(f"[{'PASS' if policy_ok else 'FAIL'}] preview={preview_ok} fix={fix_ok} warning={warning_fail} none={no_fail} diff={diff_ok} annotations={annotation_ok} checkstyle={checkstyle_ok} timings={timings_ok} max_issues={max_issues_ok}")
    if policy_ok:
        passed += 1
    else:
        failures.append("safe fixes, severity threshold, or GitHub annotation test failed")

    print("--- CLI: mission fixture (expect symbol index suppresses ALT_fnc_*) ---")
    total += 1
    mission = run_cli(str(MISSION_FIXTURE), "--json")
    mission_payload = []
    if mission.stdout.strip():
        try:
            mission_payload = json.loads(mission.stdout)
        except json.JSONDecodeError:
            mission_payload = []

    w201 = [d for d in mission_payload if str(d.get("code", "")) == "W201"]
    w202 = [d for d in mission_payload if str(d.get("code", "")) == "W202"]
    alt_w201 = [d for d in w201 if "ALT_fnc_" in str(d.get("message", ""))]
    zzz_w201 = [d for d in w201 if "ZZZ_fnc_doesNotExist" in str(d.get("message", ""))]

    mission_ok = (
        len(alt_w201) == 0
        and len(zzz_w201) == 1
        and len(w201) == 1
        and len(w202) == 0
    )
    print(
        f"[{'PASS' if mission_ok else 'FAIL'}] mission W201={len(w201)} "
        f"ALT_fnc_={len(alt_w201)} ZZZ_fnc_doesNotExist={len(zzz_w201)} W202={len(w202)}"
    )
    if mission_ok:
        passed += 1
    else:
        if alt_w201:
            failures.append(
                f"mission: {len(alt_w201)} unexpected W201 for ALT_fnc_* (symbol index not applied)"
            )
        if len(zzz_w201) != 1:
            failures.append(
                f"mission: expected exactly 1 W201 for ZZZ_fnc_doesNotExist, got {len(zzz_w201)}"
            )
        if w202:
            failures.append(
                f"mission: {len(w202)} unexpected W202 (config files must not be linted)"
            )

    print("--- CLI: modfuncs fixture (config functionTags suppress W201 for mod functions) ---")
    total += 1
    modfuncs = run_cli(str(MODFUNCS_FIXTURE), "--json")
    modfuncs_payload = []
    if modfuncs.stdout.strip():
        try:
            modfuncs_payload = json.loads(modfuncs.stdout)
        except json.JSONDecodeError:
            modfuncs_payload = []

    mod_w201 = [d for d in modfuncs_payload if str(d.get("code", "")) == "W201"]
    unknown_mod = [
        d for d in mod_w201 if "someUnknownMod_fnc_doThing" in str(d.get("message", ""))
    ]
    declared_tags = [
        d for d in mod_w201
        if any(t in str(d.get("message", "")) for t in ("ace_medical", "ace_hearing", "CBA_settings"))
    ]

    modfuncs_ok = (
        len(mod_w201) == 1
        and len(unknown_mod) == 1
        and len(declared_tags) == 0
    )
    print(
        f"[{'PASS' if modfuncs_ok else 'FAIL'}] modfuncs W201={len(mod_w201)} "
        f"unknownMod={len(unknown_mod)} declaredTagW201={len(declared_tags)}"
    )
    if modfuncs_ok:
        passed += 1
    else:
        if len(mod_w201) != 1:
            failures.append(
                f"modfuncs: expected exactly 1 W201, got {len(mod_w201)}"
            )
        if len(unknown_mod) != 1:
            failures.append(
                f"modfuncs: expected 1 W201 for someUnknownMod_fnc_doThing, got {len(unknown_mod)}"
            )
        if declared_tags:
            failures.append(
                f"modfuncs: {len(declared_tags)} unexpected W201 for declared-tag functions"
            )

    print("--- CLI: include fixture (locals from #include resolved; remapped to original file) ---")
    total += 1
    include = run_cli(str(INCLUDE_FIXTURE), "--json")
    include_payload = []
    if include.stdout.strip():
        try:
            include_payload = json.loads(include.stdout)
        except json.JSONDecodeError:
            include_payload = []

    defined_in_shared = [
        d for d in include_payload if "_definedInShared" in str(d.get("message", ""))
    ]
    undefined_elsewhere = [
        d for d in include_payload if "_undefinedElsewhere" in str(d.get("message", ""))
    ]

    include_ok = (
        len(defined_in_shared) == 0
        and len(undefined_elsewhere) == 1
        and str(undefined_elsewhere[0].get("code", "")) == "W101"
        and str(undefined_elsewhere[0].get("file", "")).endswith("main.sqf")
    )
    print(
        f"[{'PASS' if include_ok else 'FAIL'}] include defined_in_shared={len(defined_in_shared)} "
        f"undefined_elsewhere={len(undefined_elsewhere)}"
    )
    if include_ok:
        passed += 1
    else:
        if defined_in_shared:
            failures.append(
                f"include: {len(defined_in_shared)} unexpected diagnostic(s) for _definedInShared "
                "(include not resolved)"
            )
        if len(undefined_elsewhere) != 1:
            failures.append(
                f"include: expected exactly 1 diagnostic for _undefinedElsewhere, got {len(undefined_elsewhere)}"
            )
        elif undefined_elsewhere[0].get("code") != "W101":
            failures.append(
                f"include: expected W101 for _undefinedElsewhere, got {undefined_elsewhere[0].get('code')}"
            )
        elif not str(undefined_elsewhere[0].get("file", "")).endswith("main.sqf"):
            failures.append(
                f"include: expected _undefinedElsewhere to point at main.sqf, got {undefined_elsewhere[0].get('file')}"
            )

    print("--- CLI: params fixture (nested params defaults define locals) ---")
    total += 1
    params = run_cli(str(PARAMS_FIXTURE), "--json")
    params_payload = []
    if params.stdout.strip():
        try:
            params_payload = json.loads(params.stdout)
        except json.JSONDecodeError:
            params_payload = []

    failed_dismounts = [
        d for d in params_payload if "_failedDismounts" in str(d.get("message", ""))
    ]
    fastrope = [d for d in params_payload if "_fastrope" in str(d.get("message", ""))]
    not_defined = [
        d for d in params_payload
        if "_notDefined" in str(d.get("message", "")) and str(d.get("code", "")) == "W101"
    ]

    params_ok = (
        len(failed_dismounts) == 0
        and len(fastrope) == 0
        and len(not_defined) == 1
    )
    print(
        f"[{'PASS' if params_ok else 'FAIL'}] params _failedDismounts={len(failed_dismounts)} "
        f"_fastrope={len(fastrope)} _notDefined_W101={len(not_defined)}"
    )
    if params_ok:
        passed += 1
    else:
        if failed_dismounts:
            failures.append(
                f"params: {len(failed_dismounts)} unexpected diagnostic(s) for _failedDismounts"
            )
        if fastrope:
            failures.append(
                f"params: {len(fastrope)} unexpected diagnostic(s) for _fastrope"
            )
        if len(not_defined) != 1:
            failures.append(
                f"params: expected exactly 1 W101 for _notDefined, got {len(not_defined)}"
            )

    print("--- CLI: call_targets fixture (locals & collected callbacks are not W201) ---")
    total += 1
    call_targets = run_cli(str(CALL_TARGETS_FIXTURE), "--json")
    call_targets_payload = []
    if call_targets.stdout.strip():
        try:
            call_targets_payload = json.loads(call_targets.stdout)
        except json.JSONDecodeError:
            call_targets_payload = []

    w201 = [d for d in call_targets_payload if str(d.get("code", "")) == "W201"]
    zzz_w201 = [d for d in w201 if "ZZZ_fnc_stillMissing" in str(d.get("message", ""))]
    local_w201 = [d for d in w201 if "_fnc_drawCategory" in str(d.get("message", ""))]
    cb_w201 = [d for d in w201 if "myCallback" in str(d.get("message", ""))]

    call_targets_ok = (
        len(w201) == 1
        and len(zzz_w201) == 1
        and len(local_w201) == 0
        and len(cb_w201) == 0
    )
    print(
        f"[{'PASS' if call_targets_ok else 'FAIL'}] call_targets W201={len(w201)} "
        f"ZZZ_fnc_stillMissing={len(zzz_w201)} _fnc_drawCategory={len(local_w201)} "
        f"myCallback={len(cb_w201)}"
    )
    if call_targets_ok:
        passed += 1
    else:
        if len(w201) != 1:
            failures.append(
                f"call_targets: expected exactly 1 W201, got {len(w201)}"
            )
        if len(zzz_w201) != 1:
            failures.append(
                f"call_targets: expected exactly 1 W201 for ZZZ_fnc_stillMissing, got {len(zzz_w201)}"
            )
        if local_w201:
            failures.append(
                f"call_targets: {len(local_w201)} unexpected W201 for local _fnc_drawCategory"
            )
        if cb_w201:
            failures.append(
                f"call_targets: {len(cb_w201)} unexpected W201 for collected myCallback"
            )

    print("--- CLI: unknown_command fixture (exactly one W202 for roadSurface, no W101) ---")
    total += 1
    unknown_command = run_cli(str(UNKNOWN_COMMAND_FIXTURE), "--json")
    unknown_command_payload = []
    if unknown_command.stdout.strip():
        try:
            unknown_command_payload = json.loads(unknown_command.stdout)
        except json.JSONDecodeError:
            unknown_command_payload = []

    w202 = [d for d in unknown_command_payload if str(d.get("code", "")) == "W202"]
    road_w202 = [d for d in w202 if "roadSurface" in str(d.get("message", ""))]
    w101 = [d for d in unknown_command_payload if str(d.get("code", "")) == "W101"]

    unknown_command_ok = (
        len(unknown_command_payload) == 1
        and len(w202) == 1
        and len(road_w202) == 1
        and len(w101) == 0
    )
    print(
        f"[{'PASS' if unknown_command_ok else 'FAIL'}] unknown_command "
        f"total={len(unknown_command_payload)} W202={len(w202)} "
        f"roadSurface={len(road_w202)} W101={len(w101)}"
    )
    if unknown_command_ok:
        passed += 1
    else:
        if len(unknown_command_payload) != 1:
            failures.append(
                f"unknown_command: expected exactly 1 diagnostic, got {len(unknown_command_payload)}"
            )
        if len(road_w202) != 1:
            failures.append(
                f"unknown_command: expected exactly 1 W202 for roadSurface, got {len(road_w202)}"
            )
        if len(w202) != 1:
            failures.append(
                f"unknown_command: expected exactly 1 W202, got {len(w202)}"
            )
        if w101:
            failures.append(
                f"unknown_command: expected 0 W101, got {len(w101)}"
            )

    print("--- CLI: modcache fixture (mod cache auto-loaded; exact function names suppress W201) ---")
    total += 1
    modcache = run_cli(str(MODCACHE_FIXTURE), "--json")
    modcache_payload = []
    if modcache.stdout.strip():
        try:
            modcache_payload = json.loads(modcache.stdout)
        except json.JSONDecodeError:
            modcache_payload = []

    mc_w201 = [d for d in modcache_payload if str(d.get("code", "")) == "W201"]
    mc_typo = [d for d in mc_w201 if "setUnconsious" in str(d.get("message", ""))]
    mc_setunconscious = [
        d for d in mc_w201 if "setUnconscious" in str(d.get("message", ""))
    ]
    mc_putinearplugs = [
        d for d in mc_w201 if "putInEarplugs" in str(d.get("message", ""))
    ]

    modcache_ok = (
        len(mc_w201) == 1
        and len(mc_typo) == 1
        and len(mc_setunconscious) == 0
        and len(mc_putinearplugs) == 0
    )
    print(
        f"[{'PASS' if modcache_ok else 'FAIL'}] modcache W201={len(mc_w201)} "
        f"typo={len(mc_typo)} setUnconscious={len(mc_setunconscious)} "
        f"putInEarplugs={len(mc_putinearplugs)}"
    )
    if modcache_ok:
        passed += 1
    else:
        if len(mc_w201) != 1:
            failures.append(
                f"modcache: expected exactly 1 W201, got {len(mc_w201)}"
            )
        if len(mc_typo) != 1:
            failures.append(
                f"modcache: expected exactly 1 W201 for setUnconsious (typo), got {len(mc_typo)}"
            )
        if mc_setunconscious:
            failures.append(
                f"modcache: {len(mc_setunconscious)} unexpected W201 for cached setUnconscious"
            )
        if mc_putinearplugs:
            failures.append(
                f"modcache: {len(mc_putinearplugs)} unexpected W201 for cached putInEarplugs"
            )

    print("--- CLI: config_code fixture (embedded SQF in description.ext; one W201, zero W202) ---")
    total += 1
    config_code = run_cli(str(CONFIG_CODE_FIXTURE), "--json")
    config_code_payload = []
    if config_code.stdout.strip():
        try:
            config_code_payload = json.loads(config_code.stdout)
        except json.JSONDecodeError:
            config_code_payload = []

    cc_w201 = [d for d in config_code_payload if str(d.get("code", "")) == "W201"]
    cc_w202 = [d for d in config_code_payload if str(d.get("code", "")) == "W202"]
    cc_thisfn = [
        d for d in cc_w201 if "thisFunctionDoesNotExist" in str(d.get("message", ""))
    ]

    config_code_ok = (
        len(cc_w201) == 1
        and len(cc_thisfn) == 1
        and len(cc_w202) == 0
    )
    print(
        f"[{'PASS' if config_code_ok else 'FAIL'}] config_code W201={len(cc_w201)} "
        f"thisFunctionDoesNotExist={len(cc_thisfn)} W202={len(cc_w202)}"
    )
    if config_code_ok:
        passed += 1
    else:
        if len(cc_w201) != 1:
            failures.append(
                f"config_code: expected exactly 1 W201, got {len(cc_w201)}"
            )
        if len(cc_thisfn) != 1:
            failures.append(
                f"config_code: expected 1 W201 for thisFunctionDoesNotExist, got {len(cc_thisfn)}"
            )
        if cc_w202:
            failures.append(
                f"config_code: {len(cc_w202)} unexpected W202 (config structure must not be linted)"
            )

    print("--- CLI: project plugin rule ---")
    total += 1
    plugin_ok = False
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "armalint.json").write_text('{"plugins": ["rules.py"]}', encoding="utf-8")
        (root / "rules.py").write_text(
            "from armalint.diagnostic import Diagnostic, Severity\n"
            "def check(source, filename):\n"
            "    return [Diagnostic(Severity.WARNING, 'W901', 'plugin marker', 1, 1, filename)] if 'MARK' in source else []\n"
            "def register(api):\n"
            "    api.register('W901', 'warning', 'plugin marker', check)\n",
            encoding="utf-8",
        )
        source_file = root / "main.sqf"
        source_file.write_text('hint "MARK";\n', encoding="utf-8")
        plugin_proc = run_cli(str(source_file), "--json")
        try:
            plugin_payload = json.loads(plugin_proc.stdout or "[]")
            plugin_ok = any(item.get("code") == "W901" for item in plugin_payload)
        except json.JSONDecodeError:
            plugin_ok = False
    print(f"[{'PASS' if plugin_ok else 'FAIL'}] project plugin diagnostic")
    if plugin_ok:
        passed += 1
    else:
        failures.append("project plugin diagnostic was not emitted")

    print("--- summary ---")
    print(f"{passed}/{total} checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
