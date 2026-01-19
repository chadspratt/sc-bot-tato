param(
    [string]$Difficulty = ""
)

$workDir = $PSScriptRoot
$logsDir = "C:\Users\inter\Documents\StarCraft II\Replays\Multiplayer\docker"
$jobs = @()

# Create logs directory if it doesn't exist
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir
}

docker container prune -f

# Build environment variables
$envVars = @()
if ($Difficulty -ne "") {
    $envVars += "-e", "DIFFICULTY=$Difficulty"
    Write-Host "Running tests with difficulty: $Difficulty" -ForegroundColor Yellow
}

$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=protoss -e BUILD=rush @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "protoss_rush.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=protoss -e BUILD=timing @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "protoss_timing.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=protoss -e BUILD=macro @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "protoss_macro.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=protoss -e BUILD=power @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "protoss_power.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=protoss -e BUILD=air @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "protoss_air.log"), $envVars

$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=terran -e BUILD=rush @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "terran_rush.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=terran -e BUILD=timing @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "terran_timing.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=terran -e BUILD=macro @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "terran_macro.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=terran -e BUILD=power @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "terran_power.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=terran -e BUILD=air @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "terran_air.log"), $envVars

$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=zerg -e BUILD=rush @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "zerg_rush.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=zerg -e BUILD=timing @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "zerg_timing.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=zerg -e BUILD=macro @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "zerg_macro.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=zerg -e BUILD=power @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "zerg_power.log"), $envVars
$jobs += Start-Job -ScriptBlock { param($dir, $logFile, $envVars) Set-Location $dir; docker compose run --rm -e RACE=zerg -e BUILD=air @envVars bot *>&1 | Tee-Object -FilePath $logFile } -ArgumentList $workDir, (Join-Path $logsDir "zerg_air.log"), $envVars

Write-Host "Started $($jobs.Count) test jobs. Logs will be written to: $logsDir" -ForegroundColor Yellow

# Wait for jobs to complete and show their output as they finish
while ($jobs | Where-Object { $_.State -eq 'Running' }) {
    $completed = $jobs | Where-Object { $_.State -eq 'Completed' }
    foreach ($job in $completed) {
        Write-Host "`n=== Job $($job.Id) finished ===" -ForegroundColor Green
        # Receive-Job $job
        Remove-Job $job
        $jobs = $jobs | Where-Object { $_.Id -ne $job.Id }
    }
    Start-Sleep -Milliseconds 500
}

# Handle any remaining jobs
# $jobs | Receive-Job
$jobs | Remove-Job

Write-Host "`nAll tests completed. Check log files in: $logsDir" -ForegroundColor Green