# 打包游戏机助手：PyInstaller 生成程序目录 → Inno Setup 生成安装包。
# 用法（PowerShell 7）：pwsh -NoProfile -File packaging/build.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "缺少 .venv：先运行 python -m venv .venv 并安装 requirements.txt" }
& $py -m pip install --quiet pyinstaller
if ($LASTEXITCODE) { throw 'pyinstaller 安装失败' }

$version = (& $py -c "import lolhex; print(lolhex.__version__)").Trim()
Write-Host "版本 $version"

Push-Location packaging
& $py -m PyInstaller lolhex.spec --noconfirm --distpath ..\build\dist --workpath ..\build\work
$code = $LASTEXITCODE
Pop-Location
if ($code) { throw 'PyInstaller 打包失败' }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw '缺少 Inno Setup：winget install --id JRSoftware.InnoSetup -e --scope user' }
& $iscc "/DAppVersion=$version" packaging\LolHex.iss
if ($LASTEXITCODE) { throw 'Inno Setup 编译失败' }
Get-ChildItem build\installer\*.exe | ForEach-Object { '{0}  {1:N0} MB' -f $_.FullName, ($_.Length / 1MB) }
