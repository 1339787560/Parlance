[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dir = Join-Path $PSScriptRoot 'vendor\drawio'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$dest = Join-Path $dir 'viewer-static.min.js'
try {
  Invoke-WebRequest -Uri 'https://viewer.diagrams.net/js/viewer-static.min.js' -OutFile $dest -UseBasicParsing -TimeoutSec 90
  $s = (Get-Item $dest).Length
  Write-Output ('OK: ' + $s + ' bytes')
} catch {
  Write-Output ('FAIL: ' + $_.Exception.Message)
}
