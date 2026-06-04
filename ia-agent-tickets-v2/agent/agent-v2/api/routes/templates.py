"""
POST /agent/templates/extract — Extract ticket template from document text.

Nivel C (admin-only): A supervisor pastes a procedure document and SARA
uses the LLM to extract a ticket template with pre-filled fields.
"""

import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class TemplateExtractRequest(BaseModel):
    document_text: str
    user_id: int
    thread_id: str = ""


@router.post("/agent/templates/extract")
async def extract_template(payload: TemplateExtractRequest):
    """
    Extracts a ticket template from a procedure document using the LLM.

    The document text is analyzed to extract:
      - Template name
      - Suggested description
      - Relevant keywords
      - Ticket type, category, urgency suggestions

    The result is NOT auto-saved — the supervisor reviews and confirms
    before the template is stored.

    Rate limited: this uses 1 LLM call (~500 tokens). Use sparingly.
    """
    if not payload.document_text.strip():
        raise HTTPException(status_code=400, detail="document_text is required")

    if len(payload.document_text) > 8000:
        raise HTTPException(
            status_code=413,
            detail="Document too long — max 8000 characters for template extraction.",
        )

    try:
        from core.agent import get_or_create_agent
        from core.context import current_user_id

        # Set user context for Capa 4 isolation
        current_user_id.set(payload.user_id)

        agent = get_or_create_agent("supervisor")
        thread_id = payload.thread_id or f"template-extract-{payload.user_id}"

        extract_prompt = (
            f"TEXTO DEL PROCEDIMIENTO:\n\n{payload.document_text}\n\n"
            "Analiza este procedimiento y extrae una plantilla de ticket para SARA. "
            "Devuelve ÚNICAMENTE un JSON con esta estructura exacta:\n"
            "{\n"
            '  "name": "Nombre corto de la plantilla",\n'
            '  "description": "Descripción típica del problema (en voz del usuario)",\n'
            '  "keywords": "palabras clave separadas por espacios",\n'
            '  "ticket_type": "Incidencia" o "Solicitud",\n'
            '  "category": "Categoría sugerida (ej: Soporte Técnico, Redes)",\n'
            '  "urgency": "Baja / Media / Alta / Urgente",\n'
            '  "impact": "Individual / Departamental / Alto / Crítico"\n'
            "}\n\n"
            "Notas: La descripción debe estar en primera persona del usuario, "
            "como si el usuario estuviera reportando el problema. "
            "Las keywords deben cubrir sinónimos y variaciones comunes."
        )

        result = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Eres un asistente que extrae plantillas de tickets "
                            "a partir de documentos de procedimiento. "
                            "Responde SIEMPRE con JSON válido, sin markdown, "
                            "sin explicaciones adicionales."
                        ),
                    },
                    {"role": "user", "content": extract_prompt},
                ]
            },
            config={"configurable": {"thread_id": thread_id}},
        )

        # Extract the last AI message
        from langchain_core.messages import AIMessage
        response_text = ""
        for msg in result.get("messages", []):
            if isinstance(msg, AIMessage):
                response_text = msg.content
                break

        if not response_text:
            raise HTTPException(
                status_code=422,
                detail="LLM did not return a response — try again with shorter text.",
            )

        # Try to parse as JSON (LLM might wrap in markdown)
        import json as _json
        import re

        # Strip markdown code fences if present
        clean = re.sub(r"^```(?:json)?\s*", "", response_text.strip())
        clean = re.sub(r"\s*```$", "", clean)

        template = _json.loads(clean)
        return {"success": True, "template": template}

    except _json.JSONDecodeError:
        raise HTTPException(
            status_code=422,
            detail=f"LLM returned invalid JSON: {response_text[:200]}",
        )
    except Exception as exc:
        logger.exception("Template extraction failed")
        raise HTTPException(status_code=500, detail=str(exc))
