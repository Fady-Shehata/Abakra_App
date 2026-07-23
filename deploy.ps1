param(
    [string]$HostName = "165.22.78.45",
    [string]$User = "deploy",
    [string]$AppDir = "/opt/abakra/Abakra_App",
    [string]$Branch = "main",
    [string]$Service = "abakra",
    [string]$HealthUrl = "http://165.22.78.45/login"
)

$ErrorActionPreference = "Stop"

function Find-Ssh {
    $windowsSsh = "$env:WINDIR\System32\OpenSSH\ssh.exe"
    if (Test-Path -LiteralPath $windowsSsh) {
        return $windowsSsh
    }

    $cmd = Get-Command ssh -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    throw "Could not find ssh.exe. Install OpenSSH Client or run this from a shell with ssh available."
}

$ssh = Find-Ssh
$target = "$User@$HostName"

if (Get-Command git -ErrorAction SilentlyContinue) {
    $insideWorkTree = git rev-parse --is-inside-work-tree 2>$null
    if ($insideWorkTree -eq "true") {
        git fetch origin $Branch | Out-Host
        $localHead = git rev-parse HEAD
        $remoteHead = git rev-parse "origin/$Branch"
        $dirty = git status --porcelain

        if ($dirty) {
            Write-Host "Warning: local working tree has uncommitted or untracked changes." -ForegroundColor Yellow
        }

        if ($localHead -ne $remoteHead) {
            Write-Host "Warning: local HEAD is not the same as origin/$Branch." -ForegroundColor Yellow
            Write-Host "This script deploys origin/$Branch from GitHub, not unpushed local commits." -ForegroundColor Yellow
            Write-Host "Local:  $($localHead.Substring(0, 7))" -ForegroundColor Yellow
            Write-Host "GitHub: $($remoteHead.Substring(0, 7))" -ForegroundColor Yellow
        }
    }
}

Write-Host "Deploying $Branch to ${target}:$AppDir" -ForegroundColor Cyan

& $ssh $target @"
set -e
cd "$AppDir"
echo "Remote before deploy:"
git --no-pager log --oneline -1
git fetch origin "$Branch"
git merge --ff-only "origin/$Branch"
. .venv/bin/activate
pip install -r requirements.txt >/tmp/abakra-pip-install.log
sudo systemctl restart "$Service"
echo "Remote after deploy:"
git --no-pager log --oneline -1
sudo systemctl --no-pager --full status "$Service"
"@

Write-Host "Checking $HealthUrl" -ForegroundColor Cyan
$lastError = $null
for ($attempt = 1; $attempt -le 10; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 20
        Write-Host "Health check: $($response.StatusCode) $($response.StatusDescription)" -ForegroundColor Green
        exit 0
    }
    catch {
        $lastError = $_
        Write-Host "Health check attempt $attempt failed; retrying..." -ForegroundColor Yellow
        Start-Sleep -Seconds 2
    }
}

throw "Health check failed after 10 attempts. Last error: $lastError"
