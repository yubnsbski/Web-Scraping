"""Optional local conversion for JPX legacy Excel files.

JPX publishes the listed-issues table as a legacy ``.xls`` file. The core app
stays dependency-light, so this helper uses installed desktop Excel only when
the user runs the single-user local PWA on Windows. It is a convenience path,
not a server requirement.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class JpxExcelConversionError(RuntimeError):
    """Raised when a local Excel conversion could not be completed."""


def convert_legacy_xls_to_csv_with_excel(
    xls_path: str | Path,
    csv_path: str | Path,
    *,
    timeout_seconds: int = 120,
) -> str:
    """Convert a JPX legacy ``.xls`` file to UTF-8 CSV via local Excel COM."""

    if os.name != "nt":
        raise JpxExcelConversionError("Excel conversion is only available on Windows.")

    powershell = shutil.which("powershell.exe")
    if powershell is None:
        raise JpxExcelConversionError("powershell.exe was not found.")

    source = Path(xls_path).resolve()
    target = Path(csv_path).resolve()
    if not source.is_file():
        raise JpxExcelConversionError(f"Excel source file was not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)

    script = _conversion_script()
    script_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".ps1",
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(script)
            script_path = Path(handle.name)

        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-Source",
                str(source),
                "-Output",
                str(target),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise JpxExcelConversionError("Excel conversion timed out.") from exc
    finally:
        if script_path is not None:
            script_path.unlink(missing_ok=True)

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise JpxExcelConversionError(
            "Excel conversion failed." + (f" Detail: {detail}" if detail else "")
        )
    if not target.is_file():
        raise JpxExcelConversionError("Converted CSV was not created.")
    return str(target)


def _conversion_script() -> str:
    return r"""
param(
  [Parameter(Mandatory=$true)][string]$Source,
  [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference = "Stop"
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {
  $workbook = $excel.Workbooks.Open($Source)
  try {
    $xlCSVUTF8 = 62
    $workbook.SaveAs($Output, $xlCSVUTF8)
  } finally {
    $workbook.Close($false)
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($workbook) | Out-Null
  }
} finally {
  $excel.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
}
"""
