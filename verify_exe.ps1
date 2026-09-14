# Verify SmartClipboard.exe launches and runs normally
$exe = "C:\Users\liujunhao\.gemini\antigravity\scratch\smart_clipboard\dist\SmartClipboard.exe"
$proc = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 3
$alive = -not $proc.HasExited
Write-Host "Process running: $alive (PID: $($proc.Id))"
if ($alive) {
    Stop-Process -Id $proc.Id -Force
    Write-Host "Process stopped successfully. Verification PASSED!"
} else {
    Write-Host "Process exited prematurely. ExitCode: $($proc.ExitCode)"
}
