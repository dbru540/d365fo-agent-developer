param(
    [string]$PackagesRoot = "C:\Users\DavidBru\FIVEFORTY\Documents\_WORK\540\_AI\x++\D365_repo\BabilouFinOps\PackagesLocalDirectory",
    [string[]]$Packages,
    [switch]$NoViz = $true
)

$ErrorActionPreference = "Stop"

if (-not $Packages -or $Packages.Count -eq 0) {
    throw "Provide at least one package name with -Packages."
}

$graphify = Get-Command graphify -ErrorAction Stop
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$logRoot = Join-Path (Get-Location) ".omx\graphify-runs"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$logPath = Join-Path $logRoot ("wave_" + $timestamp + ".md")

"# Graphify Wave $timestamp" | Set-Content -Path $logPath -Encoding UTF8
"" | Add-Content -Path $logPath -Encoding UTF8

foreach ($package in $Packages) {
    $packagePath = Join-Path $PackagesRoot $package
    if (-not (Test-Path $packagePath)) {
        "## $package`n- status: missing package path`n" | Add-Content -Path $logPath -Encoding UTF8
        continue
    }

    Write-Host "Graphify -> $package"
    $args = @($packagePath)
    if ($NoViz) {
        $args += "--no-viz"
    }

    try {
        & $graphify.Source @args
        "## $package`n- status: completed`n- path: $packagePath`n" | Add-Content -Path $logPath -Encoding UTF8
    }
    catch {
        "## $package`n- status: failed`n- path: $packagePath`n- error: $($_.Exception.Message)`n" | Add-Content -Path $logPath -Encoding UTF8
        throw
    }
}

Write-Host "Wave log written to $logPath"
