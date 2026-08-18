"""Platform-neutral source-contract checks for the V-02 preparation package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "main_windows.go"
CORE = ROOT / "agent_core" / "agent_core_stub.py"
CORE_TEST = ROOT / "agent_core" / "test_agent_core_stub.py"
FRONTEND = ROOT / "frontend" / "index.html"
VERSIONS = ROOT / "versions.json"
REQUIRED_SCRIPTS = {
    "Build-Spike.ps1",
    "Check-WindowsEnvironment.ps1",
    "Cleanup-Spike.ps1",
    "Collect-Evidence.ps1",
    "Install-WailsCli.ps1",
    "Install-WebView2FixedRuntime.ps1",
    "Start-Spike.ps1",
    "Test-PowerShellScriptParsing.ps1",
    "Test-ValidationEvidence.ps1",
}
PROHIBITED_PRODUCT_MARKERS = ("sqlite", "pydantic", "openai", "anthropic", "schedule")


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
    require(candidates["webview2"]["version"] == "151.0.4129.78", "WebView2 version changed")

    host = HOST.read_text(encoding="utf-8")
    for marker in (
        '"github.com/wailsapp/wails/v3/pkg/application"',
        "application.New(",
        "application.WebviewWindowOptions",
        "WebviewBrowserPath",
        '"--bootstrap-file"',
        "os.Remove(bootstrapPath)",
        "one_time_bootstrap_file",
        "bootstrap_timeout_is_not_ready",
        "old_websocket_invalid_after_restart",
        "ordinary_logs_exclude_material",
        'Header.Set("Authorization", "Bearer "+material)',
    ):
        require(marker in host, f"host is missing transport marker: {marker}")
    require("127.0.0.1" in host, "host must require an IPv4 loopback endpoint")
    for marker in PROHIBITED_PRODUCT_MARKERS:
        require(marker not in host.lower(), f"host must not contain {marker!r}")
    result_type = host.split("type validationResult", 1)[1].split("type host", 1)[0]
    require("Token" not in result_type, "candidate result must not expose material")
    require("Credential" not in result_type, "candidate result must not expose material")

    core = CORE.read_text(encoding="utf-8")
    for marker in (
        'ThreadingHTTPServer(("127.0.0.1", 0)',
        "secrets.token_urlsafe(32)",
        "os.replace(temporary, path)",
        "secrets.compare_digest",
        '"/spike/ws"',
        '"/spike/http"',
        '"/spike/control/restart"',
        "event records must not contain credentials",
    ):
        require(marker in core, f"Core test double is missing {marker}")
    for marker in PROHIBITED_PRODUCT_MARKERS:
        require(marker not in core.lower(), f"Core test double must not contain {marker!r}")
    require(re.search(r'"token"\s*:\s*token', core) is not None, "bootstrap token field missing")
    require(
        "events.record(\"bootstrap_published\", endpoint_host=\"127.0.0.1\")" in core,
        "Core log must report only a safe bootstrap diagnostic",
    )

    frontend = FRONTEND.read_text(encoding="utf-8")
    for marker in ("localStorage", "sessionStorage", "indexedDB", "Authorization", "token"):
        require(marker not in frontend, f"frontend must not persist or receive transport material: {marker}")

    core_test = CORE_TEST.read_text(encoding="utf-8")
    for marker in (
        "test_loopback_dynamic_handshake_and_authentication_rejections",
        "test_restart_invalidates_old_connection_and_credential",
        "test_delayed_bootstrap_is_not_published_before_delay",
        "event log unexpectedly contains the run credential",
    ):
        require(marker in core_test, f"Core protocol test is missing {marker}")

    scripts_dir = ROOT / "scripts"
    actual_scripts = {path.name for path in scripts_dir.glob("*.ps1")}
    missing = REQUIRED_SCRIPTS - actual_scripts
    require(not missing, f"missing scripts: {sorted(missing)}")
    for script in scripts_dir.glob("*.ps1"):
        require_ascii(script)

    gitignore = (ROOT.parents[1] / ".gitignore").read_text(encoding="utf-8")
    for marker in (
        "spikes/localhost-core-transport/.evidence/",
        "spikes/localhost-core-transport/.tools/",
        "spikes/localhost-core-transport/.spike-run.json",
    ):
        require(marker in gitignore, f"generated evidence exclusion is missing: {marker}")

    report = {
        "schemaVersion": 1,
        "spike": "V-02",
        "status": "PASS",
        "hostSourceSha256": sha256(HOST),
        "coreSourceSha256": sha256(CORE),
        "checks": [
            "locked Windows and Wails candidate",
            "Wails host and one-time bootstrap source shape",
            "loopback-only dynamic Core source shape",
            "HTTP and WebSocket authentication paths",
            "restart, stale-material, and log-exclusion checks",
            "frontend has no credential or persistence surface",
            "no product-state or model markers",
            "Windows PowerShell scripts are ASCII",
        ],
    }
    if args.report_path:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("static contract: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
