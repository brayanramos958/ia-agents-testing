"""
GET /agent/llm-status — LLM provider health dashboard.

Shows which providers are active, their circuit breaker state,
and failure/success counts. Useful for debugging during demo.
"""

from fastapi import APIRouter
from core.circuit_breaker import get_all_status, _status as _provider_status
from config.settings import settings

router = APIRouter()


@router.get("/agent/llm-status")
async def get_llm_status():
    """
    Returns the status of all known LLM providers.

    Response:
    {
        "primary": "deepseek/deepseek-v4-flash",
        "timeout": 20,
        "retry_max": 2,
        "semaphore_per_worker": 5,
        "providers": {
            "deepseek/deepseek-v4-flash": {
                "state": "closed",
                "failures": 0,
                "successes": 15,
                "consecutive_failures": 0,
                ...
            }
        }
    }
    """
    providers = get_all_status()

    # Misma lógica que /health para seleccionar el modelo del provider activo
    provider = settings.llm_provider
    model = settings.ai_gateway_model if provider == "vercel" else settings.llm_model

    return {
        "llm_provider": provider,
        "llm_model": model,
        "llm_max_concurrent": settings.llm_max_concurrent,
        "llm_semaphore_timeout": settings.llm_semaphore_timeout,
        "providers": providers,
    }
