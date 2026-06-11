"""Build / compile adapters — the top rungs of the verification ladder.

Two backends:

* :class:`BuildRunner` plans (or runs) an **MSBuild** of a Visual Studio D365 project. Kept for the
  full-IDE flow; ``execute=False`` only emits the command.
* :class:`XppCompiler` drives the standalone **X++ compiler** (``xppc.exe``) directly. This is the
  one that actually closes the "does it compile?" rung WITHOUT a full AOS/Visual Studio: ``xppc.exe``
  ships in ``PackagesLocalDirectory/bin`` and compiles a single model against the package metadata,
  emitting a diagnostics log we parse into structured errors/warnings. It is Windows-only (the
  compiler is a .NET Framework assembly) and degrades gracefully — :meth:`XppCompiler.available`
  is False when ``xppc.exe`` is not on this host, so callers report "compile rung needs a Windows
  D365 host" instead of crashing.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class BuildResult:
    status: str
    command: list[str]
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""


class BuildRunner:
    def __init__(self, msbuild_executable: str = "msbuild.exe") -> None:
        self.msbuild_executable = msbuild_executable

    def build_project(
        self,
        project_path: str | Path,
        *,
        execute: bool = False,
        output_path: str | Path | None = None,
        additional_properties: dict[str, str] | None = None,
    ) -> BuildResult:
        project_path = Path(project_path)
        properties = dict(additional_properties or {})
        if output_path is not None:
            properties["OutputPath"] = str(Path(output_path))
        command = [self.msbuild_executable, str(project_path)]
        command.extend(f"/p:{key}={value}" for key, value in properties.items())
        if not execute:
            return BuildResult(status="planned", command=command)

        process = subprocess.run(command, capture_output=True, text=True, check=False)
        return BuildResult(
            status="succeeded" if process.returncode == 0 else "failed",
            command=command,
            returncode=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
        )


# --- X++ compiler (xppc.exe) --------------------------------------------------------

@dataclass(slots=True)
class Diagnostic:
    severity: str  # "error" | "warning"
    category: str  # e.g. "Compile", "ExternalReference", "Compile Fatal"
    message: str
    element: str | None = None  # dynamics://… element path, when present
    location: str | None = None  # "(line,col),(line,col)", when present


@dataclass(slots=True)
class CompileResult:
    status: str  # "succeeded" | "failed" | "unavailable"
    model: str
    returncode: int | None = None
    error_count: int = 0
    warning_count: int = 0
    diagnostics: list[Diagnostic] = field(default_factory=list)
    log_path: str | None = None
    command: list[str] = field(default_factory=list)
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "model": self.model,
            "returncode": self.returncode,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "diagnostics": [
                {"severity": d.severity, "category": d.category, "message": d.message,
                 "element": d.element, "location": d.location}
                for d in self.diagnostics
            ],
            "log_path": self.log_path,
            "command": self.command,
            "message": self.message,
        }


_SUMMARY_RE = re.compile(r"^(Errors|Warnings):\s*(\d+)\s*$")
# "<Category words> <Severity>: <rest>"  — Severity ∈ {Fatal Error, Error, Warning}
_DIAG_RE = re.compile(r"^(?P<category>.*?)\b(?P<sev>Fatal Error|Error|Warning):\s*(?P<rest>.*)$")
_ELEMENT_RE = re.compile(r"(dynamics://\S+?)(?=[:\s]|$)")
_LOCATION_RE = re.compile(r"\[(\([\d]+,[\d]+\),\([\d]+,[\d]+\))\]")


def parse_xppc_log(text: str) -> dict[str, object]:
    """Parse an ``xppc.exe`` ``-log`` file into structured diagnostics.

    The log groups diagnostics between ``===`` separators, each ``<Category> <Severity>: <msg>``,
    then a ``Errors: N`` / ``Warnings: N`` summary. Returns
    ``{error_count, warning_count, diagnostics:[Diagnostic]}``. When the summary lines are absent
    we fall back to counting parsed diagnostics so callers always get a usable count.
    """
    diagnostics: list[Diagnostic] = []
    summary_errors: int | None = None
    summary_warnings: int | None = None

    for raw in text.replace("\x00", "").splitlines():
        line = raw.strip()
        if not line or set(line) <= {"="}:
            continue
        summary = _SUMMARY_RE.match(line)
        if summary:
            if summary.group(1) == "Errors":
                summary_errors = int(summary.group(2))
            else:
                summary_warnings = int(summary.group(2))
            continue
        diag = _DIAG_RE.match(line)
        if not diag:
            continue
        sev_word = diag.group("sev")
        rest = diag.group("rest").strip()
        severity = "error" if "Error" in sev_word else "warning"
        category = (diag.group("category").strip() + (" Fatal" if sev_word == "Fatal Error" else "")).strip() or "Compile"
        element_match = _ELEMENT_RE.search(rest)
        location_match = _LOCATION_RE.search(rest)
        diagnostics.append(Diagnostic(
            severity=severity,
            category=category,
            message=rest,
            element=element_match.group(1) if element_match else None,
            location=location_match.group(1) if location_match else None,
        ))

    error_count = summary_errors if summary_errors is not None else sum(1 for d in diagnostics if d.severity == "error")
    warning_count = summary_warnings if summary_warnings is not None else sum(1 for d in diagnostics if d.severity == "warning")
    return {"error_count": error_count, "warning_count": warning_count, "diagnostics": diagnostics}


class XppCompiler:
    """Drive ``xppc.exe`` to compile a single model against the package metadata."""

    def __init__(self, packages_root: str | Path, xppc_path: str | Path | None = None) -> None:
        self.packages_root = Path(packages_root)
        self.xppc_path = Path(xppc_path) if xppc_path else (self.packages_root / "bin" / "xppc.exe")

    def available(self) -> bool:
        """True iff the X++ compiler is present on this host (it is Windows-only)."""
        return self.xppc_path.exists()

    def compile_model(
        self,
        model: str,
        *,
        output_path: str | Path,
        log_path: str | Path,
        reference_folder: str | Path | None = None,
        appchecker: bool = False,
        xref_file: str | Path | None = None,
        timeout: int = 1800,
    ) -> CompileResult:
        """Compile ``model`` and return structured diagnostics.

        ``appchecker=True`` additionally runs the Appchecker (best-practice) rules. Returns a
        ``CompileResult`` with ``status="unavailable"`` (not an exception) when ``xppc.exe`` is not
        on this host, so the caller can report the rung as "needs a Windows D365 host".
        """
        if not self.available():
            return CompileResult(
                status="unavailable", model=model,
                message=f"xppc.exe not found at {self.xppc_path} — the compile rung needs a Windows D365 host "
                        "with PackagesLocalDirectory/bin present.",
            )
        output_path = Path(output_path)
        log_path = Path(log_path)
        output_path.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        reference_folder = Path(reference_folder) if reference_folder else self.packages_root

        command = [
            str(self.xppc_path),
            f"-metadata={self.packages_root}",
            f"-modelmodule={model}",
            f"-output={output_path}",
            f"-referenceFolder={reference_folder}",
            f"-log={log_path}",
        ]
        if appchecker:
            command.append("-RunAppcheckerRules")
        if xref_file:
            command.extend(["-xref", f"-xreffile={Path(xref_file)}"])

        try:
            process = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
        except subprocess.TimeoutExpired:
            return CompileResult(status="failed", model=model, command=command,
                                 message=f"xppc.exe timed out after {timeout}s.")

        parsed = {"error_count": 0, "warning_count": 0, "diagnostics": []}
        if log_path.exists():
            parsed = parse_xppc_log(log_path.read_text(encoding="utf-8", errors="ignore"))
        error_count = int(parsed["error_count"])
        # xppc returns non-zero on failure; treat a clean log + zero exit as success.
        status = "succeeded" if (process.returncode == 0 and error_count == 0) else "failed"
        return CompileResult(
            status=status, model=model, returncode=process.returncode,
            error_count=error_count, warning_count=int(parsed["warning_count"]),
            diagnostics=list(parsed["diagnostics"]), log_path=str(log_path), command=command,
            message=(process.stdout.strip().splitlines()[-1] if process.stdout.strip() else None),
        )

    def compile_overlay(
        self,
        model: str,
        overlays: list[tuple[str, str]],
        *,
        output_path: str | Path,
        log_path: str | Path,
        appchecker: bool = False,
        timeout: int = 1800,
    ) -> CompileResult:
        """Compile freshly-generated artifacts IN CONTEXT — closes the generate->compile loop.

        ``overlays`` is a list of ``(relative_path, content)`` where ``relative_path`` is under the
        PackagesLocalDirectory (e.g. ``BABGeneralLedger/BABGeneralLedger/AxClass/Foo.xml``). Each is
        temporarily written into the PLD so the model compiles WITH the new artifact, then the PLD is
        **always restored** (added files removed, overwritten files put back) via try/finally — even
        on error/timeout. This proves generated X++ actually compiles before it is claimed done.
        """
        if not self.available():
            return CompileResult(
                status="unavailable", model=model,
                message=f"xppc.exe not found at {self.xppc_path} — the compile rung needs a Windows D365 host.",
            )
        if not overlays:
            return CompileResult(status="failed", model=model, message="No artifacts to overlay/compile.")
        backups: list[tuple[Path, bytes | None]] = []
        try:
            for relative_path, content in overlays:
                target = self.packages_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                backups.append((target, target.read_bytes() if target.exists() else None))
                target.write_text(content, encoding="utf-8")
                # xppc ALSO (re)writes compiled metadata under <package>/XppMetadata/<model>/... as a
                # byproduct; snapshot it so the finally block removes/restores it too (it does not yet
                # exist for a brand-new artifact), leaving the PLD exactly as we found it.
                meta = self._xppmetadata_path(relative_path)
                if meta is not None:
                    backups.append((meta, meta.read_bytes() if meta.exists() else None))
            result = self.compile_model(model, output_path=output_path, log_path=log_path, timeout=timeout, appchecker=appchecker)
            result.message = (result.message or "") + f" [compiled with {len(overlays)} overlaid artifact(s), PLD restored]"
            return result
        finally:
            for target, original in reversed(backups):  # restore in reverse order
                if original is None:
                    if target.exists():
                        target.unlink()
                else:
                    target.write_bytes(original)

    def _xppmetadata_path(self, relative_path: str) -> Path | None:
        """The compiled-metadata counterpart xppc writes for a source artifact: a source at
        ``<package>/<model>/<AxType>/<name>.xml`` maps to ``<package>/XppMetadata/<model>/<AxType>/<name>.xml``."""
        parts = relative_path.replace("\\", "/").split("/")
        if len(parts) < 4:
            return None
        package, model = parts[0], parts[1]
        return self.packages_root.joinpath(package, "XppMetadata", model, *parts[2:])
