param(
  [int]$TimeoutSec = 120,
  [string]$ConfigPath = (Join-Path $env:USERPROFILE ".codex\config.toml")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ConfigPath)) {
  throw "Codex config not found: $ConfigPath"
}

$backupPath = "$ConfigPath.bak-codex-apps-timeout-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -LiteralPath $ConfigPath -Destination $backupPath -Force

$text = [System.IO.File]::ReadAllText($ConfigPath, [System.Text.Encoding]::UTF8)
$sectionPattern = "(?ms)(^\[mcp_servers\.codex_apps\]\s*.*?)(?=^\[|\z)"

if ($text -match "(?m)^\[mcp_servers\.codex_apps\]\s*$") {
  $newText = [regex]::Replace($text, $sectionPattern, {
    param($match)

    $section = $match.Groups[1].Value
    if ($section -match "(?m)^startup_timeout_sec\s*=") {
      return [regex]::Replace(
        $section,
        "(?m)^startup_timeout_sec\s*=\s*\d+\s*$",
        "startup_timeout_sec = $TimeoutSec"
      )
    }

    return $section.TrimEnd() + "`r`nstartup_timeout_sec = $TimeoutSec`r`n"
  })
} else {
  $newText = $text.TrimEnd() + "`r`n`r`n[mcp_servers.codex_apps]`r`nstartup_timeout_sec = $TimeoutSec`r`n"
}

$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($ConfigPath, $newText, $utf8NoBom)

$updatedText = [System.IO.File]::ReadAllText($ConfigPath, [System.Text.Encoding]::UTF8)
if ($updatedText -notmatch "(?ms)^\[mcp_servers\.codex_apps\]\s*.*^startup_timeout_sec\s*=\s*$TimeoutSec\s*$") {
  throw "Failed to verify codex_apps startup_timeout_sec in $ConfigPath"
}

Write-Host "Updated $ConfigPath"
Write-Host "Backup  $backupPath"
Write-Host "Set [mcp_servers.codex_apps] startup_timeout_sec = $TimeoutSec"
