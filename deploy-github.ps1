param(
    [string]$Branch = "main",
    [string]$WorkflowFile = "deploy.yml",
    [string]$Repo = "",
    [string]$HealthUrl = "http://165.22.78.45/login",
    [int]$TimeoutMinutes = 20,
    [int]$PollSeconds = 10,
    [switch]$NoWait,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Args)

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $output = & git @Args 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "git $($Args -join ' ') failed: $output"
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    return ($output | Out-String).Trim()
}

function Get-GitHubRepo {
    param([string]$RemoteUrl)

    if ($RemoteUrl -match "github\.com[:/](?<owner>[^/]+)/(?<repo>[^/]+?)(?:\.git)?$") {
        return "$($Matches.owner)/$($Matches.repo)"
    }

    throw "Could not detect GitHub repository from origin remote: $RemoteUrl"
}

function Invoke-GitHubApi {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [object]$Body = $null
    )

    $token = $env:GH_TOKEN
    if (-not $token) {
        $token = $env:GITHUB_TOKEN
    }
    if (-not $token) {
        throw "Set GH_TOKEN or GITHUB_TOKEN to a GitHub personal access token with Actions workflow permission."
    }

    $headers = @{
        Authorization = "Bearer $token"
        Accept = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
    }

    $params = @{
        Method = $Method
        Uri = $Uri
        Headers = $headers
    }

    if ($null -ne $Body) {
        $params.Body = ($Body | ConvertTo-Json -Depth 8)
        $params.ContentType = "application/json"
    }

    return Invoke-RestMethod @params
}

function Assert-DeployStepSucceeded {
    param(
        [Parameter(Mandatory = $true)][string]$ApiBase,
        [Parameter(Mandatory = $true)][object]$Run
    )

    $jobs = Invoke-GitHubApi -Method "Get" -Uri "$ApiBase/actions/runs/$($Run.id)/jobs?per_page=50"
    $deployJob = $jobs.jobs | Where-Object { $_.name -eq "deploy" } | Select-Object -First 1

    if (-not $deployJob) {
        throw "Could not find a deploy job in GitHub Actions run #$($Run.run_number): $($Run.html_url)"
    }

    $deployStep = $deployJob.steps | Where-Object { $_.name -eq "Deploy on Droplet" } | Select-Object -First 1
    if (-not $deployStep) {
        throw "Could not find the 'Deploy on Droplet' step in run #$($Run.run_number): $($Run.html_url)"
    }

    if ($deployStep.conclusion -eq "skipped") {
        throw "GitHub Actions skipped deployment. Add repository secrets DO_HOST and DO_SSH_KEY, then run this script again: $($Run.html_url)"
    }

    if ($deployStep.conclusion -ne "success") {
        throw "GitHub Actions deploy step finished with '$($deployStep.conclusion)': $($Run.html_url)"
    }

    Write-Host "Verified GitHub Actions deploy step succeeded." -ForegroundColor Green
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git was not found on PATH."
}

$token = $env:GH_TOKEN
if (-not $token) {
    $token = $env:GITHUB_TOKEN
}
if (-not $token -and -not $DryRun) {
    throw "Set GH_TOKEN or GITHUB_TOKEN before running this script. The token needs permission to run GitHub Actions workflows."
}

$insideWorkTree = Invoke-Git @("rev-parse", "--is-inside-work-tree")
if ($insideWorkTree -ne "true") {
    throw "Run this script from inside the repository."
}

if (-not $Repo) {
    $originUrl = Invoke-Git @("remote", "get-url", "origin")
    $Repo = Get-GitHubRepo -RemoteUrl $originUrl
}

Write-Host "Checking GitHub branch origin/$Branch" -ForegroundColor Cyan
Invoke-Git @("fetch", "origin", $Branch) | Out-Host

$localHead = Invoke-Git @("rev-parse", "HEAD")
$remoteHead = Invoke-Git @("rev-parse", "origin/$Branch")
$dirty = Invoke-Git @("status", "--porcelain")

if ($dirty) {
    Write-Host "Warning: local working tree has uncommitted or untracked changes." -ForegroundColor Yellow
}

if ($localHead -ne $remoteHead) {
    Write-Host "Warning: local HEAD is not the same as origin/$Branch." -ForegroundColor Yellow
    Write-Host "This script deploys the latest GitHub commit, not unpushed local commits." -ForegroundColor Yellow
    Write-Host "Local:  $($localHead.Substring(0, 7))" -ForegroundColor Yellow
    Write-Host "GitHub: $($remoteHead.Substring(0, 7))" -ForegroundColor Yellow
}

Write-Host "GitHub commit to deploy: $($remoteHead.Substring(0, 7))" -ForegroundColor Cyan

if ($DryRun) {
    Write-Host "Dry run complete. Would trigger $WorkflowFile on $Repo@$Branch." -ForegroundColor Green
    exit 0
}

$apiBase = "https://api.github.com/repos/$Repo"
$dispatchUri = "$apiBase/actions/workflows/$WorkflowFile/dispatches"
$runsUri = "$apiBase/actions/workflows/$WorkflowFile/runs?branch=$Branch&event=workflow_dispatch&per_page=10"
$existingRuns = Invoke-GitHubApi -Method "Get" -Uri $runsUri
$existingRunIds = @{}
foreach ($existingRun in $existingRuns.workflow_runs) {
    $existingRunIds[[string]$existingRun.id] = $true
}

Write-Host "Triggering GitHub Actions workflow $WorkflowFile for $Repo@$Branch" -ForegroundColor Cyan
Invoke-GitHubApi -Method "Post" -Uri $dispatchUri -Body @{ ref = $Branch } | Out-Null

if ($NoWait) {
    Write-Host "Workflow dispatched. Check GitHub Actions for progress." -ForegroundColor Green
    exit 0
}

$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$run = $null

Write-Host "Waiting for GitHub Actions run..." -ForegroundColor Cyan
while ((Get-Date) -lt $deadline) {
    $runs = Invoke-GitHubApi -Method "Get" -Uri $runsUri
    $run = $runs.workflow_runs |
        Where-Object {
            $_.head_sha -eq $remoteHead -and -not $existingRunIds.ContainsKey([string]$_.id)
        } |
        Select-Object -First 1

    if ($run) {
        Write-Host "Run #$($run.run_number): $($run.status) / $($run.conclusion)" -ForegroundColor Cyan
        if ($run.status -eq "completed") {
            if ($run.conclusion -eq "success") {
                Write-Host "GitHub deployment workflow completed successfully." -ForegroundColor Green
                Write-Host $run.html_url
                Assert-DeployStepSucceeded -ApiBase $apiBase -Run $run
                break
            }

            throw "GitHub deployment workflow failed with conclusion '$($run.conclusion)': $($run.html_url)"
        }
    }

    Start-Sleep -Seconds $PollSeconds
}

if (-not $run -or $run.status -ne "completed") {
    throw "Timed out waiting for GitHub Actions deployment after $TimeoutMinutes minutes."
}

Write-Host "Checking $HealthUrl" -ForegroundColor Cyan
$response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 20
Write-Host "Health check: $($response.StatusCode) $($response.StatusDescription)" -ForegroundColor Green
