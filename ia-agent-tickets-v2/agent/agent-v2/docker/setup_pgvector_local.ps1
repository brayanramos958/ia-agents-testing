# ============================================================
#  Instala pgvector en PostgreSQL 18 local (Windows x64)
#  Ejecutar como Administrador en PowerShell
# ============================================================

$PG_VERSION   = "18"
$PG_DIR       = "C:\Program Files\PostgreSQL\$PG_VERSION"
$PG_LIB       = "$PG_DIR\lib"
$PG_EXT       = "$PG_DIR\share\extension"
$PGVECTOR_VER = "0.8.0"   # Cambiar si hay una version mas nueva en github.com/pgvector/pgvector/releases

$zipUrl   = "https://github.com/pgvector/pgvector/releases/download/v$PGVECTOR_VER/pgvector-v$PGVECTOR_VER-pg${PG_VERSION}-windows-x86_64.zip"
$zipPath  = "$env:TEMP\pgvector.zip"
$extractPath = "$env:TEMP\pgvector_install"

Write-Host "`n[1/4] Descargando pgvector v$PGVECTOR_VER para PG$PG_VERSION..."
Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing

Write-Host "[2/4] Extrayendo..."
if (Test-Path $extractPath) { Remove-Item $extractPath -Recurse -Force }
Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force

Write-Host "[3/4] Copiando archivos a $PG_DIR..."
Copy-Item "$extractPath\vector.dll"      $PG_LIB -Force
Copy-Item "$extractPath\vector.control"  $PG_EXT -Force
Copy-Item "$extractPath\vector--*.sql"   $PG_EXT -Force

Write-Host "[4/4] Creando extension en helpdesk_checkpoints..."
& "$PG_DIR\bin\psql.exe" -U postgres -d helpdesk_checkpoints `
    -c "CREATE EXTENSION IF NOT EXISTS vector;" `
    -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"

Write-Host "`nListo. pgvector instalado en PostgreSQL $PG_VERSION."
Write-Host "Si el ultimo paso fallo, ejecutalo manualmente con el usuario postgres:"
Write-Host "  psql -U postgres -d helpdesk_checkpoints -c `"CREATE EXTENSION IF NOT EXISTS vector;`""
