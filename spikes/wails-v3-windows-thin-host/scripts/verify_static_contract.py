"""Platform-neutral contract checks for the V-01 validation package.

These checks intentionally inspect source shape only. They do not make claims
about Windows desktop behavior; that requires the phase B real-machine run.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "versions.json"
HOST = ROOT / "main_windows.go"
CORE = ROOT / "agent_core" / "agent_core_stub.py"
WAILS_INSTALL = ROOT / "scripts" / "Install-WailsCli.ps1"
REQUIRED_SCRIPTS = {
    "Check-WindowsEnvironment.ps1",
    "Build-Spike.ps1",
    "Start-Spike.ps1",
    "Invoke-ProcessSupervisorScenario.ps1",
    "Record-ManualObservations.ps1",
    "Test-PowerShellScriptParsing.ps1",
    "Test-ValidationEvidence.ps1",
    "Collect-Evidence.ps1",
    "Cleanup-Spike.ps1",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    versions_raw = VERSIONS.read_bytes()
    require(versions_raw.startswith(b"\xef\xbb\xbf"), "versions.json must be UTF-8 with BOM for Windows PowerShell 5.1")
    versions = json.loads(versions_raw.decode("utf-8-sig"))
    require(versions["candidates"]["wails"]["version"] == "v3.0.0-beta.8", "Wails candidate changed")
    require(versions["candidates"]["go"]["version"] == "go1.25.0", "Go candidate changed")
    require(versions["candidates"]["python"]["version"] == "3.12.3", "Python candidate changed")
    require(versions["candidates"]["webview2"]["version"] == "151.0.4129.78", "WebView2 candidate changed")

    source = HOST.read_text(encoding="utf-8")
    for token in (
        "SingleInstanceOptions",
        "SystemTray.New",
        "AlwaysOnTop:      true",
        "EnableWithOptions",
        "SendNotificationWithActions",
        "notification_context_routed",
        "supervisor.New",
    ):
        require(token in source, f"host is missing {token}")
    for token in ("bytes.TrimPrefix", "read required .spike-run.json", "parse required .spike-run.json"):
        require(token in source, f"host must fail closed and accept a BOM in its run configuration: {token}")
    for prohibited in ("sqlite", "pydantic", "openai", "anthropic", "schedule"):
        require(prohibited not in source.lower(), f"host source must not contain {prohibited!r}")

    core = CORE.read_text(encoding="utf-8").lower()
    for prohibited in ("sqlite", "pydantic", "openai", "anthropic"):
        require(prohibited not in core, f"core test double must not contain {prohibited!r}")
    require(re.search(r'\("127\.0\.0\.1", args\.port\)', core) is not None, "core must bind loopback only")

    actual_scripts = {path.name for path in (ROOT / "scripts").glob("*.ps1")}
    missing = REQUIRED_SCRIPTS - actual_scripts
    require(not missing, f"missing required PowerShell scripts: {sorted(missing)}")
    for script in (ROOT / "scripts").glob("*.ps1"):
        raw = script.read_bytes()
        require(
            raw.startswith(b"\xef\xbb\xbf"),
            f"{script.name} must be UTF-8 with BOM for Windows PowerShell 5.1",
        )
        require(
            "Join-Path ((&" not in raw.decode("utf-8-sig"),
            f"{script.name} must not nest a command invocation inside Join-Path; bind it before joining",
        )
    wails_install = WAILS_INSTALL.read_text(encoding="utf-8-sig")
    for token in (
        "System.Diagnostics.Process",
        "RedirectStandardOutput = $true",
        "RedirectStandardError = $true",
        "$versionProcess.ExitCode",
        "[string]::IsNullOrWhiteSpace($actual)",
        "wails3 version 失败",
    ):
        require(token in wails_install, f"Install-WailsCli.ps1 must handle Wails version output: {token}")
    environment_check = (ROOT / "scripts" / "Check-WindowsEnvironment.ps1").read_text(encoding="utf-8-sig")
    for token in (
        "[Environment]::Is64BitOperatingSystem",
        "System.Diagnostics.Process",
        "wailsVersionProcess.ExitCode",
    ):
        require(token in environment_check, f"Check-WindowsEnvironment.ps1 must record Wails safely: {token}")
    build_script = (ROOT / "scripts" / "Build-Spike.ps1").read_text(encoding="utf-8-sig")
    for token in (
        "function Invoke-NativeBuildCommand",
        "RedirectStandardOutput = $true",
        "RedirectStandardError = $true",
        "ReadToEndAsync()",
        "process.ExitCode",
        "process.StartInfo.WorkingDirectory = $root",
    ):
        require(token in build_script, f"Build-Spike.ps1 must run native tools without PowerShell stderr errors: {token}")
    start_script = (ROOT / "scripts" / "Start-Spike.ps1").read_text(encoding="utf-8-sig")
    for token in ("WriteAllText", "UTF8Encoding]::new($false)"):
        require(token in start_script, f"Start-Spike.ps1 must write portable run configuration JSON: {token}")
    single_instance = (ROOT / "scripts" / "Invoke-SingleInstanceCheck.ps1").read_text(encoding="utf-8-sig")
    for token in (
        "Get-SpikeHostProcesses",
        "Get-Process -Name $hostProcessName",
        "Test-SecondInstanceEvent",
        "second_instance_activated",
        "hostsAfter.Count -eq 1",
        "当前宿主未成功加载 .spike-run.json",
    ):
        require(token in single_instance, f"single-instance check must verify process count and activation event: {token}")
    evidence_summary = (ROOT / "scripts" / "Test-ValidationEvidence.ps1").read_text(encoding="utf-8-sig")
    for token in (
        "hostBuildCommit",
        "verificationCommit",
        "singleInstanceReportPath",
        "runConfigurationLoaded",
        "'FAIL'",
    ):
        require(token in evidence_summary, f"evidence summary must preserve host/verifier identity and explicit failures: {token}")
    evidence_collection = (ROOT / "scripts" / "Collect-Evidence.ps1").read_text(encoding="utf-8-sig")
    for token in ("hostBuildCommit", "verificationCommit", "$runDir"):
        require(token in evidence_collection, f"evidence collection must select the active run and preserve identity: {token}")
    print("static contract: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
