$workDir = $PSScriptRoot
$jobs = @()

docker container prune -f

$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=protoss -e BUILD=rush bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=protoss -e BUILD=timing bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=protoss -e BUILD=macro bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=protoss -e BUILD=power bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=protoss -e BUILD=air bot } -ArgumentList $workDir

$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=terran -e BUILD=rush bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=terran -e BUILD=timing bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=terran -e BUILD=macro bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=terran -e BUILD=power bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=terran -e BUILD=air bot } -ArgumentList $workDir

$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=zerg -e BUILD=rush bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=zerg -e BUILD=timing bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=zerg -e BUILD=macro bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=zerg -e BUILD=power bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run --rm -e RACE=zerg -e BUILD=air bot } -ArgumentList $workDir

# Wait for jobs to complete and show their output as they finish
while ($jobs | Where-Object { $_.State -eq 'Running' }) {
    $completed = $jobs | Where-Object { $_.State -eq 'Completed' }
    foreach ($job in $completed) {
        Write-Host "`n=== Job $($job.Id) finished ===" -ForegroundColor Green
        Receive-Job $job
        Remove-Job $job
        $jobs = $jobs | Where-Object { $_.Id -ne $job.Id }
    }
    Start-Sleep -Milliseconds 500
}

# Handle any remaining jobs
$jobs | Receive-Job
$jobs | Remove-Job
