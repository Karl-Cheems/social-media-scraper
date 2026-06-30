$dir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$out = Join-Path $dir "lark-cli.exe"
$chunks = Get-ChildItem "$dir/lark-cli-windows.dat.*" | Sort-Object Name
$stream = [System.IO.File]::OpenWrite($out)
foreach ($chunk in $chunks) { $bytes = [System.IO.File]::ReadAllBytes($chunk.FullName); $stream.Write($bytes,0,$bytes.Length) }
$stream.Close()
Write-Host "Done: $out"
