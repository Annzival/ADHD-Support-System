"""Platform-neutral source-contract checks for the V-03 preparation package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "main_windows.go"
CORE = ROOT / "agent_core" / "synthetic_core.py"
CORE_TEST = ROOT / "agent_core" / "test_synthetic_core.py"
BOOTSTRAP_SUPERVISOR = ROOT / "bootstrap_supervisor.go"
BOOTSTRAP_TIMEOUT_TEST = ROOT / "bootstrap_timeout_test.go"
FRONTEND = ROOT / "frontend" / "index.html"
VERSIONS = ROOT / "versions.json"
REQUIRED_SCRIPTS = {
    "Build-Spike.ps1",
    "Check-WindowsEnvironment.ps1",
    "Cleanup-Spike.ps1",
    "Collect-Evidence.ps1",
    "Install-WailsCli.ps1",
    "Install-WebView2FixedRuntime.ps1",
    "Prepare-RebootCheckpoint.ps1",
    "Start-RecoveryValidation.ps1",
    "Test-PowerShellScriptParsing.ps1",
    "Test-ValidationEvidence.ps1",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_ascii(path: Path) -> None:
    try:
        path.read_bytes().decode("ascii")
    except UnicodeDecodeError as error:
        raise AssertionError(f"{path.name} must remain ASCII for Windows PowerShell 5.1") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()

    versions = json.loads(VERSIONS.read_text(encoding="utf-8"))
    candidates = versions["candidates"]
    require(candidates["windows"]["release"] == "22H2", "Windows release changed")
    require(candidates["windows"]["architecture"] == "x64", "Windows architecture changed")
    require(candidates["wails"]["version"] == "v3.0.0-beta.8", "Wails version changed")
    require(candidates["go"]["version"] == "go1.25.0", "Go version changed")
    require(candidates["python"]["version"] == "3.12.3", "Python version changed")
    require(candidates["python"]["architecture"] == "amd64", "Python architecture changed")
    require(candidates["python"]["processBits"] == 64, "Python process bitness changed")
    require(candidates["webview2"]["version"] == "151.0.4129.78", "WebView2 version changed")

    host = HOST.read_text(encoding="utf-8")
    for marker in (
        '"github.com/wailsapp/wails/v3/pkg/application"',
        "application.New(",
        "WebviewBrowserPath",
        '"--bootstrap-file"',
        "os.Remove(bootstrapPath)",
        "one_time_bootstrap_file",
        "normal-exit",
        "h.startCore(parent)",
        "startCoreCommand(",
        "HandshakeTimeoutMillis)*time.Millisecond",
        "record.Token",
    ):
        require(marker in host, f"host is missing required boundary marker: {marker}")
    require("sqlite" not in host.lower(), "host must not contain a direct SQLite dependency")
    for marker in ("os.Open(h.config.DatabasePath)", "os.ReadFile(h.config.DatabasePath)", "database/sql"):
        require(marker not in host, f"host must not access the database: {marker}")
    result_type = host.split("type validationResult", 1)[1].split("type host", 1)[0]
    require("Token" not in result_type, "candidate result must not expose temporary material")
    require("Authorization" not in result_type, "candidate result must not expose temporary material")

    bootstrap_supervisor = BOOTSTRAP_SUPERVISOR.read_text(encoding="utf-8")
    for marker in (
        "context.WithTimeout(parent, handshakeTimeout)",
        "errBootstrapTimeout",
        "cleanupFailedBootstrap",
        "core.stop()",
        "os.RemoveAll(handoffDirectory)",
    ):
        require(marker in bootstrap_supervisor, f"bootstrap timeout supervisor is missing {marker}")
    bootstrap_timeout_test = BOOTSTRAP_TIMEOUT_TEST.read_text(encoding="utf-8")
    for marker in (
        "TestStartCoreCommandTimesOutWhenLiveCoreDoesNotPublishBootstrap",
        "V03_TEST_LIVE_CORE_WITHOUT_BOOTSTRAP",
        "errBootstrapTimeout",
        "command.ProcessState.Exited()",
        "os.ErrNotExist",
    ):
        require(marker in bootstrap_timeout_test, f"bootstrap timeout test is missing {marker}")

    core = CORE.read_text(encoding="utf-8")
    for marker in (
        "sqlite3.connect",
        "PRAGMA journal_mode = WAL",
        "BEGIN IMMEDIATE",
        "os._exit(73)",
        "SYNTHETIC_AUTHORITY_ID",
        "SYNTHETIC_FUTURE_ID",
        "SYNTHETIC_EXPIRED_ID",
        "INSERT OR IGNORE INTO synthetic_observable",
        'ThreadingHTTPServer(("127.0.0.1", 0)',
        "write_private_bootstrap",
        "synthetic event records must not contain credentials",
    ):
        require(marker in core, f"Core is missing required recovery marker: {marker}")
    for forbidden in ("pydantic", "openai", "anthropic", "model provider", "user plan"):
        require(forbidden not in core.lower(), f"Core contains prohibited product marker: {forbidden}")

    tests = CORE_TEST.read_text(encoding="utf-8")
    for marker in (
        "test_prepare_preserves_committed_data_and_rolls_back_interrupted_write",
        "test_prepare_cli_writes_a_sanitized_summary",
        "test_recovery_scan_is_idempotent_for_the_synthetic_records",
        "test_loopback_bootstrap_and_core_restart_keep_one_time_recovery_results",
        "test_interrupted_mode_exits_with_the_controlled_code",
    ):
        require(marker in tests, f"Core test is missing {marker}")

    frontend = FRONTEND.read_text(encoding="utf-8")
    for marker in ("localStorage", "sessionStorage", "indexedDB", "Authorization", "token"):
        require(marker not in frontend, f"frontend must not persist or receive material: {marker}")

    scripts_dir = ROOT / "scripts"
    scripts = {path.name for path in scripts_dir.glob("*.ps1")}
    require(REQUIRED_SCRIPTS <= scripts, f"missing scripts: {sorted(REQUIRED_SCRIPTS - scripts)}")
    for script in scripts_dir.glob("*.ps1"):
        require_ascii(script)

    environment_check = (scripts_dir / "Check-WindowsEnvironment.ps1").read_text(encoding="ascii")
    for marker in ("processBits", "struct.calcsize(\"P\") * 8", "python_3_12_3_x64"):
        require(marker in environment_check, f"environment check is missing {marker}")
    restart_script = (scripts_dir / "Start-RecoveryValidation.ps1").read_text(encoding="ascii")
    for marker in ("LastBootUpTime", "host-ready.json", "process-count.json", "databasePath"):
        require(marker in restart_script, f"restart validation is missing {marker}")
    collector = (scripts_dir / "Collect-Evidence.ps1").read_text(encoding="ascii")
    for marker in ("v03-evidence-summary", "Raw evidence archive SHA-256", "databaseIdentity"):
        require(marker in collector, f"collector is missing {marker}")

    gitignore = (ROOT.parents[1] / ".gitignore").read_text(encoding="utf-8")
    for marker in (
        "spikes/sqlite-restart-recovery/.evidence/",
        "spikes/sqlite-restart-recovery/.tools/",
        "spikes/sqlite-restart-recovery/.spike-run.json",
    ):
        require(marker in gitignore, f"generated evidence exclusion is missing: {marker}")

    report = {
        "schemaVersion": 1,
        "spike": "V-03",
        "status": "PASS",
        "hostSourceSha256": sha256(HOST),
        "coreSourceSha256": sha256(CORE),
        "checks": [
            "locked Windows and Python candidates",
            "Python-only SQLite transaction and recovery boundary",
            "synthetic committed and interrupted-write scenarios",
            "idempotent synthetic future and expired-record recovery",
            "one-time loopback bootstrap and Core restart path",
            "bounded bootstrap timeout stops and reaps an unbootstrapped Core",
            "thin host has no direct database dependency",
            "Windows reboot, process-count, and evidence scripts",
            "PowerShell ASCII compatibility",
        ],
    }
    if args.report_path:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("static contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
