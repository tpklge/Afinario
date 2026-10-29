param([string]$Installer)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $Installer) {
    $Installer = (Get-ChildItem -LiteralPath (Join-Path $projectDirectory 'dist\installers') -Filter '*-setup.exe' |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{7D512EBC-B0D6-438D-9CF0-E0BDA545CB29}_is1'
if (Test-Path -LiteralPath $uninstallKey) {
    throw 'Já existe uma instalação Afinário. Execute o teste do instalador em uma conta/máquina limpa.'
}
$testDirectory = Join-Path ([IO.Path]::GetTempPath()) ('Afinario teste ' + [guid]::NewGuid())
$installDirectory = Join-Path $testDirectory 'Aplicativo com espaços'
[IO.Directory]::CreateDirectory($testDirectory) | Out-Null
$reportDirectory = Join-Path $projectDirectory 'reports'
[IO.Directory]::CreateDirectory($reportDirectory) | Out-Null
$installLog = Join-Path $reportDirectory 'installer-smoke.log'
$report = Join-Path $testDirectory 'bundle-check.json'
$arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS', '/MERGETASKS=!desktopicon',
    "/DIR=`"$installDirectory`"", "/LOG=`"$installLog`"")
$process = Start-Process -FilePath $Installer -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0) { throw "Instalação falhou: $($process.ExitCode)" }
$previousPath = $env:PATH
$previousQt = $env:QT_QPA_PLATFORM
try {
    # Only Windows system tools remain discoverable, never Python or external audio tools.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    $executable = Join-Path $installDirectory 'Afinario.exe'
    $process = Start-Process -FilePath $executable -ArgumentList @('--self-test', "`"$report`"") -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit(120000)) {
        Stop-Process -Id $process.Id
        throw 'Verificação excedeu o tempo limite.'
    }
    if (-not (Test-Path -LiteralPath $report)) { throw 'O executável não gerou o relatório.' }
    $result = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
    Copy-Item -LiteralPath $report -Destination (Join-Path $reportDirectory 'installer-bundle-check.json')
    if (-not $result.ok) { throw "Falha no pacote: $($result.error)" }
    if ($result.python_on_path) { throw 'O teste encontrou Python no PATH e não comprova o isolamento.' }
    Write-Output 'Instalação e execução sem Python/FFmpeg no PATH: OK.'
} finally {
    $env:PATH = $previousPath
    if ($null -eq $previousQt) {
        Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    } else { $env:QT_QPA_PLATFORM = $previousQt }
    $uninstaller = Join-Path $installDirectory 'unins000.exe'
    if (Test-Path -LiteralPath $uninstaller) {
        $process = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru -WindowStyle Hidden
        if ($process.ExitCode -ne 0) { throw 'Falha ao desinstalar o pacote de teste.' }
    }
}
