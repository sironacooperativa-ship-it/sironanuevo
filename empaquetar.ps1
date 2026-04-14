# Genera un .zip del código SIRONA (sin venv, sin base local, sin staticfiles generados).
# Uso: .\empaquetar.ps1
#       .\empaquetar.ps1 -Salida "C:\MisArchivos\SIRONA.zip"

param(
    [string]$Salida = ""
)

$ErrorActionPreference = "Stop"
$proyecto = $PSScriptRoot
$nombre = "SIRONA-sistema_$(Get-Date -Format 'yyyy-MM-dd_HHmm')"
if (-not $Salida) {
    $padre = Split-Path $proyecto -Parent
    $Salida = Join-Path $padre "$nombre.zip"
}

$temp = Join-Path $env:TEMP "sirona_empaquetar_$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $temp -Force | Out-Null

try {
    # /E todo; /XD excluye carpetas con ese nombre en cualquier nivel; /XF archivos
    $null = robocopy $proyecto $temp /E `
        /XD .venv __pycache__ .git staticfiles .mypy_cache .pytest_cache node_modules `
        /XF db.sqlite3 *.pyc `
        /NFL /NDL /NJH /NJS /NC /NS /NP
    $rc = $LASTEXITCODE
    if ($rc -ge 8) {
        throw "robocopy falló con código $rc"
    }

    if (-not (Test-Path (Join-Path $temp "manage.py"))) {
        throw "No se copió manage.py; revisá la ruta del proyecto."
    }

    Compress-Archive -Path (Join-Path $temp '*') -DestinationPath $Salida -Force
    Write-Host "Paquete creado: $Salida"
}
finally {
    if (Test-Path $temp) {
        Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
