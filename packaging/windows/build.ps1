param([switch]$SkipSync)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location -LiteralPath $projectDirectory
try {
    if (-not $SkipSync) {
        & uv sync --locked --extra gui --extra recognition --extra windows-build
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar as dependências.' }
    }
    $buildPython = Join-Path $projectDirectory '.venv\Scripts\python.exe'
    & $buildPython packaging/windows/prepare.py
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao preparar as ferramentas.' }
    $compilerDirectory = Join-Path $projectDirectory '.tools\inno'
    $compiler = Join-Path $compilerDirectory 'ISCC.exe'
    if (-not (Test-Path -LiteralPath $compiler)) {
        $innoInstaller = Join-Path $projectDirectory '.tools\innosetup-7.1.1-x64.exe'
        $signature = Get-AuthenticodeSignature -LiteralPath $innoInstaller
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys') {
            throw 'Assinatura do instalador Inno Setup inválida.'
        }
        $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', "/DIR=`"$compilerDirectory`"")
        $setupProcess = Start-Process -FilePath $innoInstaller -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
        if ($setupProcess.ExitCode -ne 0) { throw 'Falha ao preparar o compilador Inno Setup.' }
    }
    $buildLogDirectory = Join-Path $projectDirectory 'build'
    Write-Output 'Empacotando Python, Qt e provedores...'
    $buildProcess = Start-Process -FilePath $buildPython -ArgumentList @('-m', 'PyInstaller', '--noconfirm', '--clean', 'packaging/windows/Afinario.spec') -WorkingDirectory $projectDirectory -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $buildLogDirectory 'pyinstaller.stdout.log') -RedirectStandardError (Join-Path $buildLogDirectory 'pyinstaller.stderr.log')
    if ($buildProcess.ExitCode -ne 0) { throw 'Falha no empacotamento. Consulte build/pyinstaller.stderr.log.' }
    $version = & $buildPython -c "import importlib.metadata; print(importlib.metadata.version('afinario'))"
    & $compiler /Q "/DAppVersion=$version" packaging/windows/Afinario.iss
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar o instalador.' }
    Get-ChildItem -LiteralPath (Join-Path $projectDirectory 'dist\installers') -Filter '*-setup.exe' | ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        [IO.File]::WriteAllText($_.FullName + '.sha256', "$hash  $($_.Name)`n", [Text.Encoding]::ASCII)
    }
} finally {
    Pop-Location
}
