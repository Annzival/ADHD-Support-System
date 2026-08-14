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
    "Invoke-OverlayCloseRecovery.ps1",
    "Collect-OverlayCloseRecoveryEvidence.ps1",
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
    overlay_close_hook = re.compile(
        r'h\.overlay\.RegisterHook\(events\.Common\.WindowClosing,\s*'
        r'func\(event \*application\.WindowEvent\) \{\s*'
        r'event\.Cancel\(\)\s*'
        r'h\.overlay\.Hide\(\)\s*'
        r'h\.logger\.record\("overlay_hidden_on_close",',
        re.DOTALL,
    )
    require(
        overlay_close_hook.search(source) is not None,
        "overlay native close must cancel destruction, hide the existing window, and record overlay_hidden_on_close",
    )
    for token in ("overlay_shown", 'h.app.Window.GetByName("overlay")', "overlay_destroyed_before_show"):
        require(token in source, f"overlay close-recovery diagnostics are missing {token}")
    for prohibited in ("sqlite", "pydantic", "openai", "anthropic", "schedule"):
        require(prohibited not in source.lower(), f"host source must not contain {prohibited!r}")

    core = CORE.read_text(encoding="utf-8").lower()
    for prohibited in ("sqlite", "pydantic", "openai", "anthropic"):
        require(prohibited not in core, f"core test double must not contain {prohibited!r}")
    require(re.search(r'\("127\.0\.0\.1", args\.port\)', core) is not None, "core must bind loopback only")

    actual_scripts = {path.name for path in (ROOT / "scripts").glob("*.ps1")}
    missing = REQUIRED_SCRIPTS - actual_scripts
    require(not missing, f"missing required PowerShell scripts: {sorted(missing)}")
    for script in (ROOT / "scripts").rglob("*.ps1"):
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
        "buildCommit = $buildCommit",
        ".spike-build.json",
    ):
        require(token in build_script, f"Build-Spike.ps1 must run native tools without PowerShell stderr errors: {token}")
    start_script = (ROOT / "scripts" / "Start-Spike.ps1").read_text(encoding="utf-8-sig")
    for token in (
        "WriteAllText",
        "UTF8Encoding]::new($false)",
        "Get-Process -Name $hostProcessName",
        "host_starting",
        "配置未被证实已加载",
        ".spike-build.json",
        "hostBuildCommit = $buildMarker.buildCommit",
        "hostBinarySha256 = $actualBinarySha256",
    ):
        require(token in start_script, f"Start-Spike.ps1 must write portable run configuration JSON: {token}")
    cleanup_script = (ROOT / "scripts" / "Cleanup-Spike.ps1").read_text(encoding="utf-8-sig")
    require(
        "Get-Process -Name $hostProcessName" in cleanup_script,
        "Cleanup-Spike.ps1 must find the host without WMI executable-path visibility",
    )
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
    supervisor_scenario = (ROOT / "scripts" / "Invoke-ProcessSupervisorScenario.ps1").read_text(encoding="utf-8-sig")
    for token in (
        "SupervisorEvidence.ps1",
        "Wait-SupervisorAttemptEvidence",
        "eventEvidence.passed",
        "passed = [string]::IsNullOrEmpty($failure)",
        "process-supervisor-$Scenario.json",
    ):
        require(token in supervisor_scenario, f"supervisor scenario must expect a single crash restart and preserve a failure report: {token}")
    require(
        "$becameUnhealthy" not in supervisor_scenario,
        "supervisor scenario must not require a transient HTTP-unhealthy observation",
    )
    supervisor_replay = ROOT / "scripts" / "tests" / "Test-SupervisorEvidence.ps1"
    require(supervisor_replay.exists(), "captured supervisor trace replay test is missing")
    evidence_summary = (ROOT / "scripts" / "Test-ValidationEvidence.ps1").read_text(encoding="utf-8-sig")
    for token in (
        "hostBuildCommits",
        "verificationCommit",
        "excludedRuns",
        "singleInstanceReports",
        "'FAIL'",
    ):
        require(token in evidence_summary, f"evidence summary must preserve host/verifier identity and explicit failures: {token}")
    evidence_collection = (ROOT / "scripts" / "Collect-Evidence.ps1").read_text(encoding="utf-8-sig")
    for token in ("hostBuildCommits", "verificationCommit", "excludedRuns"):
        require(token in evidence_collection, f"evidence collection must select the active run and preserve identity: {token}")
    overlay_recovery = (ROOT / "scripts" / "Invoke-OverlayCloseRecovery.ps1").read_text(encoding="utf-8-sig")
    for token in (
        "overlay_hidden_on_close",
        "overlay_shown",
        "overlay_destroyed_before_show",
        "for ($round = 1; $round -le 3; $round++)",
        "overlay-close-recovery.json",
    ):
        require(token in overlay_recovery, f"overlay close-recovery script must collect three-round evidence: {token}")
    overlay_collection = (ROOT / "scripts" / "Collect-OverlayCloseRecoveryEvidence.ps1").read_text(encoding="utf-8-sig")
    for token in (
        "rawEvidenceArchive",
        "controlledLocation",
        "retention",
        "absolute paths",
        "overlay-close-recovery-summary",
    ):
        require(token in overlay_collection, f"overlay evidence collector is missing sanitized-summary metadata: {token}")
    print("static contract: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
