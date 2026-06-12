"""
Metrics metadata registry — Fase 1.7 del PLAN_METRICS.md.

Provides a central registry of ALL metrics exposed by the agent,
including their definition, calculation method, SLO targets, and
freshness information. This is the foundation for traceability and
audit — every metric in the codebase should be documented here.

Why this matters:
  - Developers know exactly what each metric measures
  - Auditors/compliance can trace the lineage of any number
  - The Odoo dashboard can show "what does this KPI mean?" tooltips
  - Future contributors know where to add new metrics

Architecture:
  - metrics_metadata table in PostgreSQL (single source of truth)
  - Seeded on first import with all existing metrics
  - Queried via the catalog endpoints (/agent/metrics/catalog)

Public API:
    MetricsRegistry().get_all()           -> list of all metrics
    MetricsRegistry().get_by_name(name)   -> single metric metadata
    MetricsRegistry().get_by_category(c)  -> metrics in a category
"""

from typing import List, Optional
import psycopg

from config.settings import settings


# ── Seed data: every metric in the system must be here ────────────────────

SEED_METRICS = [
    # ── Summary KPIs (9) ─────────────────────────────────────────────────
    {
        "metric_name": "satisfaction_pct",
        "description": "% de ratings >=4 sobre 5 estrellas en feedback (escala 0-100)",
        "category": "summary",
        "unit": "percentage",
        "data_source": "agent_feedback",
        "calculation_method": "AVG(rating) * 100 / 5",
        "sql_query": "SELECT AVG(rating) * 100.0 / 5 FROM agent_feedback",
        "refresh_frequency": "realtime",
        "slo_target": 80.0,
        "slo_alert_threshold": 70.0,
    },
    {
        "metric_name": "deflection_pct",
        "description": "% de mensajes donde SARA dio solución SIN crear ticket (0-100)",
        "category": "summary",
        "unit": "percentage",
        "data_source": "agent_feedback",
        "calculation_method": "(solution_suggested / total_feedback) * 100",
        "sql_query": "SELECT (COUNT(*) FILTER (WHERE feedback_type = 'solution_suggested') * 100.0 / COUNT(*)) FROM agent_feedback",
        "refresh_frequency": "realtime",
        "slo_target": 40.0,
        "slo_alert_threshold": 30.0,
    },
    {
        "metric_name": "rag_hit_rate_pct",
        "description": "% de queries RAG que encontraron >=1 doc con score > threshold (0-100)",
        "category": "summary",
        "unit": "percentage",
        "data_source": "rag_usage",
        "calculation_method": "(hits / total_calls) * 100",
        "sql_query": "SELECT (SUM(solutions_found) * 100.0 / COUNT(*)) FROM rag_usage",
        "refresh_frequency": "realtime",
        "slo_target": 60.0,
        "slo_alert_threshold": 40.0,
    },
    {
        "metric_name": "avg_resolution_hours",
        "description": "Promedio de horas entre ticket creado y ticket resuelto",
        "category": "summary",
        "unit": "hours",
        "data_source": "odoo_backend",
        "calculation_method": "AVG(time_to_resolve)",
        "sql_query": "Computed in OdooAdapter.get_operation_metrics()",
        "refresh_frequency": "hourly",
        "slo_target": 24.0,
        "slo_alert_threshold": 48.0,
    },
    {
        "metric_name": "sla_breach_count",
        "description": "Tickets activos con deadline < NOW() en PostgreSQL",
        "category": "summary",
        "unit": "count",
        "data_source": "sla_alerts",
        "calculation_method": "COUNT(*) WHERE alert_type = 'expired' AND acknowledged_by IS NULL",
        "sql_query": "SELECT COUNT(*) FROM sla_alerts WHERE alert_type = 'expired' AND acknowledged_by IS NULL",
        "refresh_frequency": "realtime",
        "slo_target": 0.0,
        "slo_alert_threshold": 3.0,
    },
    {
        "metric_name": "total_cost_usd",
        "description": "Suma acumulada de cost_usd en llm_usage (USD)",
        "category": "summary",
        "unit": "usd",
        "data_source": "llm_usage",
        "calculation_method": "SUM(cost_usd)",
        "sql_query": "SELECT SUM(cost_usd) FROM llm_usage",
        "refresh_frequency": "realtime",
        "slo_target": 50.0,
        "slo_alert_threshold": 100.0,
    },
    {
        "metric_name": "total_llm_calls",
        "description": "Conteo total de invocaciones LLM",
        "category": "summary",
        "unit": "count",
        "data_source": "llm_usage",
        "calculation_method": "COUNT(*)",
        "sql_query": "SELECT COUNT(*) FROM llm_usage",
        "refresh_frequency": "realtime",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "total_open_tickets",
        "description": "Tickets en estado != 'Resuelto' en Odoo",
        "category": "summary",
        "unit": "count",
        "data_source": "odoo_backend",
        "calculation_method": "COUNT(*) WHERE stage_id != 12",
        "sql_query": "Computed in OdooAdapter.get_operation_metrics()",
        "refresh_frequency": "hourly",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "total_resolved_tickets",
        "description": "Tickets en estado 'Resuelto' en Odoo (ID=12)",
        "category": "summary",
        "unit": "count",
        "data_source": "odoo_backend",
        "calculation_method": "COUNT(*) WHERE stage_id = 12",
        "sql_query": "Computed in OdooAdapter.get_operation_metrics()",
        "refresh_frequency": "hourly",
        "slo_target": None,
        "slo_alert_threshold": None,
    },

    # ── Feedback (6) ─────────────────────────────────────────────────────
    {
        "metric_name": "total_feedback",
        "description": "Conteo total de feedback recibido (todas las fuentes)",
        "category": "feedback",
        "unit": "count",
        "data_source": "agent_feedback",
        "calculation_method": "COUNT(*)",
        "sql_query": "SELECT COUNT(*) FROM agent_feedback",
        "refresh_frequency": "realtime",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "avg_satisfaction",
        "description": "Rating promedio (escala 1-5)",
        "category": "feedback",
        "unit": "rating",
        "data_source": "agent_feedback",
        "calculation_method": "AVG(rating)",
        "sql_query": "SELECT AVG(rating) FROM agent_feedback",
        "refresh_frequency": "realtime",
        "slo_target": 4.0,
        "slo_alert_threshold": 3.5,
    },
    {
        "metric_name": "tickets_created",
        "description": "Tickets creados por usuarios asistidos por SARA",
        "category": "feedback",
        "unit": "count",
        "data_source": "agent_feedback",
        "calculation_method": "COUNT(*) WHERE feedback_type = 'ticket_created'",
        "sql_query": "SELECT COUNT(*) FROM agent_feedback WHERE feedback_type = 'ticket_created'",
        "refresh_frequency": "realtime",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "tickets_deflected",
        "description": "Tickets que SARA resolvió sin crear (deflexión)",
        "category": "feedback",
        "unit": "count",
        "data_source": "agent_feedback",
        "calculation_method": "COUNT(*) WHERE feedback_type = 'solution_suggested'",
        "sql_query": "SELECT COUNT(*) FROM agent_feedback WHERE feedback_type = 'solution_suggested'",
        "refresh_frequency": "realtime",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "deflection_rate_pct",
        "description": "Tasa de deflexión: deflectados / total * 100 (0-100)",
        "category": "feedback",
        "unit": "percentage",
        "data_source": "agent_feedback",
        "calculation_method": "(tickets_deflected / total_feedback) * 100",
        "sql_query": "SELECT (COUNT(*) FILTER (WHERE feedback_type = 'solution_suggested') * 100.0 / COUNT(*)) FROM agent_feedback",
        "refresh_frequency": "realtime",
        "slo_target": 40.0,
        "slo_alert_threshold": 30.0,
    },

    # ── Operation (10) ───────────────────────────────────────────────────
    {
        "metric_name": "avg_time_to_assign_hours",
        "description": "Promedio de horas entre ticket creado y asignación a resolutor",
        "category": "operation",
        "unit": "hours",
        "data_source": "odoo_backend",
        "calculation_method": "AVG(assign_time - create_time)",
        "sql_query": "Computed in OdooAdapter.get_operation_metrics()",
        "refresh_frequency": "hourly",
        "slo_target": 4.0,
        "slo_alert_threshold": 12.0,
    },
    {
        "metric_name": "avg_time_to_resolve_hours",
        "description": "Promedio de horas entre ticket creado y ticket resuelto",
        "category": "operation",
        "unit": "hours",
        "data_source": "odoo_backend",
        "calculation_method": "AVG(resolve_time - create_time)",
        "sql_query": "Computed in OdooAdapter.get_operation_metrics()",
        "refresh_frequency": "hourly",
        "slo_target": 24.0,
        "slo_alert_threshold": 48.0,
    },
    {
        "metric_name": "tickets_by_category",
        "description": "Distribución de tickets por categoría (GROUP BY category)",
        "category": "operation",
        "unit": "object",
        "data_source": "odoo_backend",
        "calculation_method": "GROUP BY category, COUNT(*)",
        "sql_query": "Computed in OdooAdapter.get_operation_metrics()",
        "refresh_frequency": "hourly",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "tickets_by_urgency",
        "description": "Distribución de tickets por nivel de urgencia",
        "category": "operation",
        "unit": "object",
        "data_source": "odoo_backend",
        "calculation_method": "GROUP BY urgency, COUNT(*)",
        "sql_query": "Computed in OdooAdapter.get_operation_metrics()",
        "refresh_frequency": "hourly",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "tickets_by_status",
        "description": "Conteo de tickets por estado (status)",
        "category": "operation",
        "unit": "object",
        "data_source": "odoo_backend",
        "calculation_method": "GROUP BY status, COUNT(*)",
        "sql_query": "Computed in OdooAdapter.get_operation_metrics()",
        "refresh_frequency": "hourly",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "approval_rate",
        "description": "{approved, rejected, pending} de tickets en flujo de aprobación",
        "category": "operation",
        "unit": "object",
        "data_source": "odoo_backend",
        "calculation_method": "COUNT by approval status",
        "sql_query": "Computed in OdooAdapter.get_operation_metrics()",
        "refresh_frequency": "hourly",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "sla_at_risk_count",
        "description": "Tickets con deadline < NOW() + 2h (en riesgo)",
        "category": "operation",
        "unit": "count",
        "data_source": "sla_alerts",
        "calculation_method": "COUNT(*) WHERE alert_type = 'expires_soon' AND acknowledged_by IS NULL",
        "sql_query": "SELECT COUNT(*) FROM sla_alerts WHERE alert_type = 'expires_soon' AND acknowledged_by IS NULL",
        "refresh_frequency": "realtime",
        "slo_target": 3.0,
        "slo_alert_threshold": 5.0,
    },
    {
        "metric_name": "reopen_rate_pct",
        "description": "% de tickets resueltos que fueron reabiertos (0-100)",
        "category": "operation",
        "unit": "percentage",
        "data_source": "odoo_backend",
        "calculation_method": "(reopened / resolved) * 100",
        "sql_query": "Computed in OdooAdapter.get_operation_metrics()",
        "refresh_frequency": "hourly",
        "slo_target": 5.0,
        "slo_alert_threshold": 10.0,
    },

    # ── RAG (5) ─────────────────────────────────────────────────────────
    {
        "metric_name": "rag_total_calls",
        "description": "Conteo total de llamadas a suggest_solution() (RAG)",
        "category": "rag",
        "unit": "count",
        "data_source": "rag_usage",
        "calculation_method": "COUNT(*)",
        "sql_query": "SELECT COUNT(*) FROM rag_usage",
        "refresh_frequency": "realtime",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "rag_hits",
        "description": "Conteo de queries RAG que encontraron >=1 documento",
        "category": "rag",
        "unit": "count",
        "data_source": "rag_usage",
        "calculation_method": "SUM(solutions_found)",
        "sql_query": "SELECT SUM(solutions_found) FROM rag_usage",
        "refresh_frequency": "realtime",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "rag_hit_rate",
        "description": "Tasa de hits RAG (0-1) — multiplicar por 100 para porcentaje",
        "category": "rag",
        "unit": "ratio",
        "data_source": "rag_usage",
        "calculation_method": "hits / total_calls",
        "sql_query": "SELECT SUM(solutions_found)::float / COUNT(*) FROM rag_usage",
        "refresh_frequency": "realtime",
        "slo_target": 0.6,
        "slo_alert_threshold": 0.4,
    },
    {
        "metric_name": "rag_avg_score",
        "description": "Score promedio de similitud (0-1) de docs encontrados",
        "category": "rag",
        "unit": "score",
        "data_source": "rag_usage",
        "calculation_method": "AVG(top_score) WHERE solutions_found = TRUE",
        "sql_query": "SELECT AVG(top_score) FROM rag_usage WHERE solutions_found = 1",
        "refresh_frequency": "realtime",
        "slo_target": 0.7,
        "slo_alert_threshold": 0.5,
    },
    {
        "metric_name": "rag_avg_latency_ms",
        "description": "Latencia promedio de queries RAG en milisegundos",
        "category": "rag",
        "unit": "ms",
        "data_source": "rag_usage",
        "calculation_method": "AVG(latency_ms)",
        "sql_query": "SELECT AVG(latency_ms) FROM rag_usage",
        "refresh_frequency": "realtime",
        "slo_target": 500.0,
        "slo_alert_threshold": 1000.0,
    },

    # ── LLM (10) ────────────────────────────────────────────────────────
    {
        "metric_name": "llm_total_calls",
        "description": "Conteo total de invocaciones al LLM",
        "category": "llm",
        "unit": "count",
        "data_source": "llm_usage",
        "calculation_method": "COUNT(*)",
        "sql_query": "SELECT COUNT(*) FROM llm_usage",
        "refresh_frequency": "realtime",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "llm_total_tokens",
        "description": "Tokens totales consumidos (input + output)",
        "category": "llm",
        "unit": "count",
        "data_source": "llm_usage",
        "calculation_method": "SUM(tokens_total)",
        "sql_query": "SELECT SUM(tokens_total) FROM llm_usage",
        "refresh_frequency": "realtime",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "llm_avg_latency_ms",
        "description": "Latencia promedio de llamadas LLM",
        "category": "llm",
        "unit": "ms",
        "data_source": "llm_usage",
        "calculation_method": "AVG(latency_ms)",
        "sql_query": "SELECT AVG(latency_ms) FROM llm_usage",
        "refresh_frequency": "realtime",
        "slo_target": 3000.0,
        "slo_alert_threshold": 5000.0,
    },
    {
        "metric_name": "llm_fallback_count",
        "description": "Conteo de veces que se activó un fallback a otro provider",
        "category": "llm",
        "unit": "count",
        "data_source": "llm_usage",
        "calculation_method": "SUM(fallback_triggered)",
        "sql_query": "SELECT SUM(fallback_triggered) FROM llm_usage",
        "refresh_frequency": "realtime",
        "slo_target": None,
        "slo_alert_threshold": None,
    },
    {
        "metric_name": "llm_fallback_rate",
        "description": "Tasa de fallback (0-1) — multiplicar por 100 para porcentaje",
        "category": "llm",
        "unit": "ratio",
        "data_source": "llm_usage",
        "calculation_method": "fallback_count / total_calls",
        "sql_query": "SELECT SUM(fallback_triggered)::float / COUNT(*) FROM llm_usage",
        "refresh_frequency": "realtime",
        "slo_target": 0.05,
        "slo_alert_threshold": 0.15,
    },
    {
        "metric_name": "llm_error_count",
        "description": "Conteo de llamadas LLM que terminaron con error",
        "category": "llm",
        "unit": "count",
        "data_source": "llm_usage",
        "calculation_method": "COUNT(*) WHERE error != ''",
        "sql_query": "SELECT COUNT(*) FROM llm_usage WHERE error != ''",
        "refresh_frequency": "realtime",
        "slo_target": 0.0,
        "slo_alert_threshold": 10.0,
    },
    {
        "metric_name": "llm_error_rate",
        "description": "Tasa de error LLM (0-1) — multiplicar por 100 para porcentaje",
        "category": "llm",
        "unit": "ratio",
        "data_source": "llm_usage",
        "calculation_method": "error_count / total_calls",
        "sql_query": "SELECT (COUNT(*) FILTER (WHERE error != ''))::float / COUNT(*) FROM llm_usage",
        "refresh_frequency": "realtime",
        "slo_target": 0.02,
        "slo_alert_threshold": 0.05,
    },
]


def _ensure_schema() -> None:
    """Create metrics_metadata table and seed it. Idempotent."""
    dsn = settings.postgres_dsn
    if not dsn:
        raise RuntimeError("settings.postgres_dsn is not configured")

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS metrics_metadata (
                    metric_name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    data_source TEXT NOT NULL,
                    calculation_method TEXT NOT NULL,
                    sql_query TEXT,
                    refresh_frequency TEXT NOT NULL,
                    last_calculated_at TIMESTAMPTZ,
                    slo_target REAL,
                    slo_alert_threshold REAL
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_metadata_category
                ON metrics_metadata(category)
            """)

            # Seed (INSERT ... ON CONFLICT DO NOTHING — idempotent)
            for m in SEED_METRICS:
                cur.execute("""
                    INSERT INTO metrics_metadata
                    (metric_name, description, category, unit, data_source,
                     calculation_method, sql_query, refresh_frequency,
                     slo_target, slo_alert_threshold)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (metric_name) DO NOTHING
                """, (
                    m["metric_name"],
                    m["description"],
                    m["category"],
                    m["unit"],
                    m["data_source"],
                    m["calculation_method"],
                    m.get("sql_query"),
                    m["refresh_frequency"],
                    m.get("slo_target"),
                    m.get("slo_alert_threshold"),
                ))


# Run on first import
_ensure_schema()


class MetricsRegistry:
    """
    Read-only registry of all metrics in the system.

    Thread-safe: each query opens its own short-lived psycopg connection
    (same pattern as FeedbackCollector).
    """

    def __init__(self, dsn: Optional[str] = None):
        self._dsn = dsn or settings.postgres_dsn
        if not self._dsn:
            raise RuntimeError("MetricsRegistry requires settings.postgres_dsn")

    def get_all(self) -> List[dict]:
        """Return ALL metrics in the catalog, ordered by category then name."""
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT metric_name, description, category, unit,
                           data_source, calculation_method, sql_query,
                           refresh_frequency, last_calculated_at,
                           slo_target, slo_alert_threshold
                    FROM metrics_metadata
                    ORDER BY category, metric_name
                """)
                rows = cur.fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_by_name(self, name: str) -> Optional[dict]:
        """Return a single metric metadata by name, or None if not found."""
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT metric_name, description, category, unit,
                           data_source, calculation_method, sql_query,
                           refresh_frequency, last_calculated_at,
                           slo_target, slo_alert_threshold
                    FROM metrics_metadata
                    WHERE metric_name = %s
                """, (name,))
                row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_category(self, category: str) -> List[dict]:
        """Return all metrics in a given category."""
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT metric_name, description, category, unit,
                           data_source, calculation_method, sql_query,
                           refresh_frequency, last_calculated_at,
                           slo_target, slo_alert_threshold
                    FROM metrics_metadata
                    WHERE category = %s
                    ORDER BY metric_name
                """, (category,))
                rows = cur.fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_categories(self) -> List[str]:
        """Return distinct categories (useful for navigation)."""
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT category
                    FROM metrics_metadata
                    ORDER BY category
                """)
                return [r[0] for r in cur.fetchall()]

    def update_last_calculated(self, metric_name: str) -> None:
        """Touch last_calculated_at to NOW(). Called after computing a metric."""
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE metrics_metadata
                    SET last_calculated_at = NOW()
                    WHERE metric_name = %s
                """, (metric_name,))

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "metric_name": row[0],
            "description": row[1],
            "category": row[2],
            "unit": row[3],
            "data_source": row[4],
            "calculation_method": row[5],
            "sql_query": row[6],
            "refresh_frequency": row[7],
            "last_calculated_at": row[8].isoformat() if row[8] else None,
            "slo_target": row[9],
            "slo_alert_threshold": row[10],
        }
