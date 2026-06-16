try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5001/health' -TimeoutSec 3 -ErrorAction Stop
    Write-Host "Status: $($r.StatusCode)"
    Write-Host "Body: $($r.Content)"
} catch {
    Write-Host "Error: $($_.Exception.Message)"
}