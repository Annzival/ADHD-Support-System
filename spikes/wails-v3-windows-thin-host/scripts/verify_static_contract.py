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
    versions = json.loads(VERSIONS.read_text(encoding="utf-8"))
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
    print("static contract: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
