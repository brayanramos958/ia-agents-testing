"""
GET /metrics-plus — Dashboard HTML para visualizar las 34 métricas del agente.

Sirve una página estática que consume la API /agent/metrics del agente.
Pensado para abrirse desde el menú "Métricas Plus" en Odoo.

Diseño: copia el estilo del dashboard "Métricas SARA" existente
(panel morado, cards con borde izquierdo, paleta #4a6cf7).
"""
import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()

STATIC_DIR = Path(__file__).parent.parent.parent / "static" / "metrics-plus"


@router.get("/metrics-plus", response_class=HTMLResponse)
async def metrics_plus_dashboard():
    """Sirve el HTML principal del dashboard."""
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse(
            content="<h1>Dashboard not found</h1><p>index.html missing</p>",
            status_code=500,
        )
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@router.get("/metrics-plus/{file_name}")
async def metrics_plus_static(file_name: str):
    """Sirve archivos estáticos (app.js, style.css)."""
    # Seguridad: solo archivos en STATIC_DIR, sin path traversal
    safe_name = Path(file_name).name
    file_path = STATIC_DIR / safe_name
    if not file_path.exists() or not file_path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)

    # Content-type según extensión
    if safe_name.endswith(".js"):
        media_type = "application/javascript"
    elif safe_name.endswith(".css"):
        media_type = "text/css"
    else:
        media_type = "application/octet-stream"

    return FileResponse(file_path, media_type=media_type)
