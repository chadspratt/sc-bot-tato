$workDir = $PSScriptRoot
$jobs = @()

$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=protoss -e BUILD=rush bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=protoss -e BUILD=timing bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=protoss -e BUILD=macro bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=protoss -e BUILD=power bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=protoss -e BUILD=air bot } -ArgumentList $workDir

$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=terran -e BUILD=rush bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=terran -e BUILD=timing bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=terran -e BUILD=macro bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=terran -e BUILD=power bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=terran -e BUILD=air bot } -ArgumentList $workDir

$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=zerg -e BUILD=rush bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=zerg -e BUILD=timing bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=zerg -e BUILD=macro bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=zerg -e BUILD=power bot } -ArgumentList $workDir
$jobs += Start-Job -ScriptBlock { param($dir) Set-Location $dir; docker compose run -e RACE=zerg -e BUILD=air bot } -ArgumentList $workDir

# Wait for all jobs to complete and show their output
$jobs | Wait-Job | Receive-Job
$jobs | Remove-Job
