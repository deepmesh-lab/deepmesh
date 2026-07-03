# run_all.ps1 - benign/attack traffic collection (PowerShell native, ASCII-only)
#
# Avoids WSL/Git-Bash python path issues by running in PowerShell where
# python/locust/docker already work.
#
# Run:
#   cd deepmesh-temp-ai\data-collection
#   powershell -ExecutionPolicy Bypass -File .\run_all.ps1 all
#   (phase: benign | attack | all)
#
# Tunables (env): BENIGN_DURATION(180) ATTACK_DURATION(120) USERS(15) SPAWN(5) ID_RANGE(300)
# Preprocess (X_benign/X_attack .npy) needs .so + scapy -> run separately (see end).

param([string]$Phase = "all")
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$BENIGN = if ($env:BENIGN_DURATION) { [int]$env:BENIGN_DURATION } else { 180 }
$ATTACK = if ($env:ATTACK_DURATION) { [int]$env:ATTACK_DURATION } else { 120 }
$USERS  = if ($env:USERS)  { [int]$env:USERS }  else { 15 }
$SPAWN  = if ($env:SPAWN)  { [int]$env:SPAWN }  else { 5 }
if (-not $env:ID_RANGE) { $env:ID_RANGE = "300" }
$PY = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$SNIFFER = "nicolaka/netshoot"

$AUTH="http://localhost:8080"; $POSTU="http://localhost:8082"
$COMMENTU="http://localhost:8081"; $FRONTU="http://localhost:3000"

function Log($m){ Write-Host "`n[$(Get-Date -Format HH:mm:ss)] $m" -ForegroundColor Cyan }

# Capture eth0 of target container netns (background job). timeout ends it after dur sec.
function Start-Capture($container,$pcapDir,$dur){
  New-Item -ItemType Directory -Force -Path $pcapDir | Out-Null
  $abs = (Resolve-Path $pcapDir).Path -replace '\\','/'
  $file = "{0}_{1}.pcap" -f $container,(Get-Date -Format yyyyMMdd_HHmmss)
  Start-Job -ScriptBlock {
    param($c,$abs,$file,$dur,$img)
    docker run --rm --net "container:$c" -v "${abs}:/cap" $img timeout $dur tcpdump -i eth0 -w "/cap/$file" tcp
  } -ArgumentList $container,$abs,$file,$dur,$SNIFFER
}

# Capture (bg) + locust (fg) at the same time
function CapLoad($container,$pcapDir,$lf,$lhost,$dur,$envMap){
  $job = Start-Capture $container $pcapDir $dur
  Start-Sleep -Seconds 2
  if ($envMap) { foreach($k in $envMap.Keys){ Set-Item "env:$k" $envMap[$k] } }
  & $PY -m locust -f $lf --host $lhost --users $USERS --spawn-rate $SPAWN --run-time "$($dur)s" --headless
  Wait-Job $job -Timeout ($dur + 120) | Out-Null
  Receive-Job $job -ErrorAction SilentlyContinue | Out-Null
  Remove-Job $job -Force -ErrorAction SilentlyContinue
}

function Preflight {
  Log "PREFLIGHT"
  Write-Host ("PYTHON = {0}" -f (& $PY -c "import sys;print(sys.executable)" 2>$null))
  & $PY -c "import locust" 2>$null; if (-not $?) { & $PY -m pip install -q locust }
  docker ps *> $null; if (-not $?) { Write-Host "[warn] docker not working - check Docker Desktop" -ForegroundColor Yellow }
}

function Phase-Benign {
  Log "BENIGN auth";     CapLoad "auth-service"    ".\pcap\auth-service"    "locust\auth_locustfile.py"            $AUTH     $BENIGN @{}
  Log "BENIGN post";     CapLoad "post-service"    ".\pcap\post-service"    "locust\post_locustfile.py"            $POSTU    $BENIGN @{HOST=$POSTU;AUTH_HOST=$AUTH}
  Log "BENIGN comment";  CapLoad "comment-service" ".\pcap\comment-service" "locust\comment_locustfile.py"         $COMMENTU $BENIGN @{HOST=$COMMENTU;AUTH_HOST=$AUTH;POST_HOST=$POSTU}
  Log "BENIGN frontend"; CapLoad "frontend"        ".\pcap\frontend"        "locust\benign_frontend_locustfile.py" $FRONTU   $BENIGN @{}

  Log "BENIGN db (byproduct) - capture mysql while 3 backends load"
  $cap = Start-Capture "deepmesh-mysql" ".\pcap\mysql" $BENIGN
  Start-Sleep -Seconds 2
  $env:HOST=$AUTH
  $p1 = Start-Process -PassThru -NoNewWindow $PY -ArgumentList "-m","locust","-f","locust\auth_locustfile.py","--host",$AUTH,"--users",$USERS,"--spawn-rate",$SPAWN,"--run-time","$($BENIGN)s","--headless"
  $env:HOST=$POSTU; $env:AUTH_HOST=$AUTH
  $p2 = Start-Process -PassThru -NoNewWindow $PY -ArgumentList "-m","locust","-f","locust\post_locustfile.py","--host",$POSTU,"--users",$USERS,"--spawn-rate",$SPAWN,"--run-time","$($BENIGN)s","--headless"
  $env:HOST=$COMMENTU; $env:AUTH_HOST=$AUTH; $env:POST_HOST=$POSTU
  $p3 = Start-Process -PassThru -NoNewWindow $PY -ArgumentList "-m","locust","-f","locust\comment_locustfile.py","--host",$COMMENTU,"--users",$USERS,"--spawn-rate",$SPAWN,"--run-time","$($BENIGN)s","--headless"
  $p1,$p2,$p3 | Wait-Process -ErrorAction SilentlyContinue
  Wait-Job $cap -Timeout ($BENIGN + 120) | Out-Null; Remove-Job $cap -Force -ErrorAction SilentlyContinue
}

function Phase-Attack {
  Log "ATTACK auth";     CapLoad "auth-service"    ".\pcap\attacks\auth-service"    "attacks\attack_auth_locustfile.py"     $AUTH     $ATTACK @{}
  Log "ATTACK post";     CapLoad "post-service"    ".\pcap\attacks\post-service"    "attacks\attack_post_locustfile.py"     $POSTU    $ATTACK @{HOST=$POSTU;AUTH_HOST=$AUTH}
  Log "ATTACK comment";  CapLoad "comment-service" ".\pcap\attacks\comment-service" "attacks\attack_comment_locustfile.py"  $COMMENTU $ATTACK @{HOST=$COMMENTU;AUTH_HOST=$AUTH;POST_HOST=$POSTU}
  Log "ATTACK frontend"; CapLoad "frontend"        ".\pcap\attacks\frontend"        "attacks\attack_frontend_locustfile.py" $FRONTU   $ATTACK @{}

  Log "ATTACK db - capture mysql + attack_db.py (cross-DB)"
  & $PY -c "import pymysql" 2>$null; if (-not $?) { & $PY -m pip install -q pymysql }
  $pw = "rootpassword"
  if (Test-Path ..\msa\.env) { $m = Select-String -Path ..\msa\.env -Pattern '^MYSQL_ROOT_PASSWORD=(.*)$'; if ($m) { $pw = $m.Matches[0].Groups[1].Value } }
  $env:MYSQL_ROOT_PASSWORD = $pw
  $cap = Start-Capture "deepmesh-mysql" ".\pcap\attacks\mysql" $ATTACK
  Start-Sleep -Seconds 2
  & $PY attacks\attack_db.py --duration $ATTACK
  Wait-Job $cap -Timeout ($ATTACK + 120) | Out-Null; Remove-Job $cap -Force -ErrorAction SilentlyContinue
}

switch ($Phase) {
  "benign"  { Preflight; Phase-Benign }
  "attack"  { Preflight; Phase-Attack }
  "all"     { Preflight; Phase-Benign; Phase-Attack }
  default   { Write-Host "phase: benign | attack | all"; exit 1 }
}

Log "DONE ($Phase)"
Write-Host "Next - preprocess (needs .so + scapy), run per service:"
Write-Host "  cd ..\model-training"
Write-Host "  python preprocess_deepmesh.py --benign ..\data-collection\pcap\<svc>\*.pcap --attack ..\data-collection\pcap\attacks\<svc>\*.pcap --out .\data\<svc> --parser-so ..\servicemesh\proxy\packet_parser_stack.so"
