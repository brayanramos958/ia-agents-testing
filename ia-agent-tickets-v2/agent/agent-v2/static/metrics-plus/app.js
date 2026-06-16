/**
 * SARA Métricas Plus — Dashboard JS.
 * Consume /agent/metrics, /agent/metrics/catalog, /agent/metrics/audit, etc.
 * Auto-refresh cada 30s.
 */
(function () {
    'use strict';

    // En producción se inyecta vía Odoo proxy; en dev usamos X-Agent-Key directo.
    const API_KEY = window.SARA_API_KEY || 'dev-key-change-in-prod';
    // URL base del agente. Al abrir desde Odoo (:8069) las peticiones relativas
    // irían a Odoo, no al agente. Forzamos URL absoluta.
    const AGENT_BASE = window.SARA_AGENT_URL || 'http://localhost:8001';
    const REFRESH_MS = 30000;

    const HEADERS = { 'X-Agent-Key': API_KEY };

    // ── Helpers ─────────────────────────────────────────────────────────────
    function setKpi(key, value, format) {
        const el = document.querySelector(`[data-kpi="${key}"] .sara-kpi-value`);
        if (!el) return;
        el.textContent = format ? format(value) : (value != null ? value : '—');
    }

    function fmtPct(v) {
        if (v == null) return '—';
        return `${(Number(v) * 100).toFixed(1)}%`;
    }

    function fmtNum(v) {
        if (v == null) return '—';
        const n = Number(v);
        return n.toLocaleString('es-ES', { maximumFractionDigits: 2 });
    }

    function fmtUsd(v) {
        if (v == null) return '—';
        return `$${Number(v).toFixed(2)}`;
    }

    function fmtHours(v) {
        if (v == null) return '—';
        return `${Number(v).toFixed(1)}h`;
    }

    function setLoading(selector) {
        const el = document.querySelector(selector);
        if (el) el.innerHTML = '<div class="sara-loading">Cargando…</div>';
    }

    function setError(selector, msg) {
        const el = document.querySelector(selector);
        if (el) el.innerHTML = `<div class="sara-error">Error: ${msg}</div>`;
    }

    async function fetchJson(path) {
        const url = `${AGENT_BASE}${path}`;
        console.log('Fetching:', url);
        try {
            const r = await fetch(url, { headers: HEADERS });
            console.log('Response:', path, r.status);
            if (!r.ok) {
                const text = await r.text();
                throw new Error(`HTTP ${r.status} on ${path}: ${text.substring(0,200)}`);
            }
            return await r.json();
        } catch (err) {
            console.error('Fetch error:', path, err);
            throw err;
        }
    }

    // ── Render por sección ──────────────────────────────────────────────────
    function renderLlmConfig(data) {
        const el = document.querySelector('[data-llm-config]');
        if (!el || !data) return;
        const cb = data.circuit_breaker || {};
        const providers = Object.values(cb).map(p =>
            `<div class="sara-llm-item">
                <div class="sara-llm-label">Provider</div>
                <strong>${p.name || '—'}</strong>
            </div>`
        ).join('');
        el.innerHTML = `
            <div class="sara-llm-item">
                <div class="sara-llm-label">Provider activo</div>
                <strong>${data.llm_provider || '—'}</strong>
            </div>
            <div class="sara-llm-item">
                <div class="sara-llm-label">Modelo</div>
                <strong>${data.llm_model || '—'}</strong>
            </div>
            <div class="sara-llm-item">
                <div class="sara-llm-label">Max concurrent</div>
                <strong>${data.llm_max_concurrent || '—'}</strong>
            </div>
            <div class="sara-llm-item">
                <div class="sara-llm-label">Semáforo timeout (s)</div>
                <strong>${data.llm_semaphore_timeout || '—'}</strong>
            </div>
            ${providers}
        `;
    }

    function renderSection(selector, data, fieldMap) {
        const el = document.querySelector(selector);
        if (!el || !data) return;
        const rows = fieldMap
            .filter(([key]) => data[key] != null)
            .map(([key, label, formatter]) => {
                const v = data[key];
                let cls = 'sara-detail-value';
                let formatted = fmtNum(v);

                if (typeof formatter === 'function') {
                    formatted = formatter(v);
                } else if (formatter && typeof formatter === 'object') {
                    // formatter = { fmt: function, cls: function }
                    if (typeof formatter.fmt === 'function') {
                        formatted = formatter.fmt(v);
                    }
                    if (typeof formatter.cls === 'function') {
                        cls = formatter.cls(v);
                    }
                }

                return `<div class="sara-detail-row">
                    <span class="sara-detail-label">${label}</span>
                    <span class="${cls}">${formatted}</span>
                </div>`;
            }).join('');
        el.innerHTML = rows || '<div class="sara-loading">Sin datos</div>';
    }

    // Helper: clasificador de salud para RAG hit rate
    const ragCls = v => v >= 0.5 ? 'sara-detail-value-good' : (v >= 0.2 ? 'sara-detail-value-warn' : 'sara-detail-value-bad');
    const ragFmt = v => fmtPct(v);
    const ragFmtScore = v => v != null ? v.toFixed(3) : '—';
    const costCls = v => v < 1 ? 'sara-detail-value-good' : (v < 10 ? 'sara-detail-value-warn' : 'sara-detail-value-bad');

    function renderLlmDetails(data) {
        renderSection('[data-llm-details]', data, [
            ['total_calls', 'Total llamadas', fmtNum],
            ['total_tokens', 'Tokens totales', fmtNum],
            ['total_input_tokens', 'Tokens input', fmtNum],
            ['total_output_tokens', 'Tokens output', fmtNum],
            ['avg_latency_ms', 'Latencia promedio (ms)', fmtNum],
            ['total_cost_usd', 'Costo total (USD)', { fmt: fmtUsd, cls: costCls }],
            ['fallback_count', 'Fallbacks usados', fmtNum],
        ]);
    }

    function renderRagDetails(data) {
        renderSection('[data-rag-details]', data, [
            ['rag_total_calls', 'Llamadas totales', fmtNum],
            ['rag_hits', 'Hits', fmtNum],
            ['rag_hit_rate', 'Hit rate', { fmt: ragFmt, cls: ragCls }],
            ['rag_avg_score', 'Score promedio', { fmt: ragFmtScore, cls: () => 'sara-detail-value' }],
            ['rag_avg_latency_ms', 'Latencia promedio (ms)', fmtNum],
        ]);
    }

    function renderOpDetails(data) {
        renderSection('[data-op-details]', data, [
            ['avg_time_to_assign_hours', 'MTTN (horas)', fmtHours],
            ['avg_time_to_resolve_hours', 'MTTR (horas)', fmtHours],
            ['reopen_rate', 'Reopen rate', fmtPct],
            ['approval_rate', 'Approval rate', fmtPct],
        ]);
    }

    function renderFeedbackDetails(data) {
        renderSection('[data-feedback-details]', data, [
            ['total_feedback', 'Total feedback', fmtNum],
            ['avg_satisfaction', 'Satisfacción promedio', v => v != null ? `${Number(v).toFixed(2)} / 5` : '—'],
            ['tickets_created', 'Tickets creados', fmtNum],
            ['tickets_deflected', 'Tickets deflected', fmtNum],
            ['deflection_rate_pct', 'Deflection rate', fmtPct],
        ]);
    }

    function renderAdoptionDetails(data) {
        renderSection('[data-adoption-details]', data, [
            ['unique_users_daily', 'DAU (daily active users)', fmtNum],
            ['unique_users_weekly', 'WAU (weekly)', fmtNum],
            ['unique_users_monthly', 'MAU (monthly)', fmtNum],
            ['usage_daily_count', 'Sesiones hoy', fmtNum],
            ['usage_weekly_count', 'Sesiones semana', fmtNum],
            ['usage_monthly_count', 'Sesiones mes', fmtNum],
            ['retention_rate_pct', 'Retention rate', fmtPct],
        ]);
    }

    function renderCreationDetails(data) {
        renderSection('[data-creation-details]', data, [
            ['tickets_created_daily', 'Tickets creados hoy', fmtNum],
            ['tickets_created_weekly', 'Tickets creados semana', fmtNum],
            ['avg_creation_time_seconds', 'Tiempo promedio creación (s)', v => v != null ? `${Number(v).toFixed(1)}s` : '—'],
            ['median_creation_time_seconds', 'Mediana creación (s)', v => v != null ? `${Number(v).toFixed(1)}s` : '—'],
            ['p95_creation_time_seconds', 'P95 creación (s)', v => v != null ? `${Number(v).toFixed(1)}s` : '—'],
            ['tickets_abandoned_count', 'Tickets abandonados', fmtNum],
            ['abandoned_rate_pct', 'Tasa de abandono', fmtPct],
        ]);
    }

    function renderCatalog(data) {
        const el = document.querySelector('[data-catalog-details]');
        if (!el) return;
        const metrics = data.metrics || [];
        const countEl = document.querySelector('[data-catalog-count]');
        if (countEl) countEl.textContent = metrics.length;

        el.innerHTML = metrics.map(m => `
            <div class="sara-catalog-item">
                <div>
                    <div class="sara-catalog-name">${m.metric_name || '—'}</div>
                    <div class="sara-catalog-desc">${m.description || ''}</div>
                </div>
                <div class="sara-catalog-category">${m.category || '—'}</div>
                <div class="sara-catalog-slo">SLO: ${m.slo_target || '—'}</div>
            </div>
        `).join('') || '<div class="sara-loading">Sin métricas catalogadas</div>';
    }

    function renderAudit(data) {
        const el = document.querySelector('[data-audit-details]');
        if (!el) return;
        const entries = data.entries || data.audit || [];
        el.innerHTML = entries.slice(0, 20).map(e => `
            <div class="sara-audit-item">
                <div class="sara-audit-time">${(e.timestamp || e.created_at || '').slice(0, 19)}</div>
                <div class="sara-audit-action">${e.action || e.event || '—'}</div>
                <div class="sara-audit-user">${e.user || e.user_id || '—'}</div>
            </div>
        `).join('') || '<div class="sara-loading">Sin entradas de audit</div>';
    }

    // ── Update timestamp ────────────────────────────────────────────────────
    function updateTimestamp() {
        const el = document.querySelector('[data-last-update]');
        if (el) el.textContent = `Última actualización: ${new Date().toLocaleTimeString('es-ES')}`;
    }

    // ── Carga principal ─────────────────────────────────────────────────────
    let isRefreshing = false;

    async function refresh() {
        if (isRefreshing) return;
        isRefreshing = true;
        const btn = document.querySelector('.sara-refresh-btn');
        if (btn) btn.disabled = true;

        try {
            // KPIs principales desde /agent/metrics (summary)
            const metrics = await fetchJson('/agent/metrics');
            const s = metrics.summary || {};
            const a = metrics.adoption || {};
            const c = metrics.creation || {};
            setKpi('satisfaction_pct', s.satisfaction_pct, fmtPct);
            setKpi('deflection_pct', s.deflection_pct, fmtPct);
            setKpi('rag_hit_rate_pct', s.rag_hit_rate_pct, fmtPct);
            setKpi('avg_resolution_hours', s.avg_resolution_hours, fmtHours);
            setKpi('sla_breach_count', s.sla_breach_count, fmtNum);
            setKpi('total_cost_usd', s.total_cost_usd, fmtUsd);
            setKpi('unique_users_monthly', a.unique_users_monthly, fmtNum);
            setKpi('tickets_abandoned_count', c.tickets_abandoned_count, fmtNum);

            // Secciones de detalle
            renderLlmDetails(metrics.llm || {});
            renderRagDetails(metrics.rag || {});
            renderOpDetails(metrics.operation || {});
            renderFeedbackDetails(metrics.feedback || {});
            renderAdoptionDetails(metrics.adoption || {});
            renderCreationDetails(metrics.creation || {});

            // LLM status
            try {
                const llmStatus = await fetchJson('/agent/llm-status');
                renderLlmConfig(llmStatus);
            } catch (e) {
                console.warn('LLM status failed:', e);
            }

            // Catalog (las 34 métricas)
            try {
                const catalog = await fetchJson('/agent/metrics/catalog');
                renderCatalog(catalog);
            } catch (e) {
                console.warn('Catalog failed:', e);
            }

            // Audit
            try {
                const audit = await fetchJson('/agent/metrics/audit');
                renderAudit(audit);
            } catch (e) {
                console.warn('Audit failed:', e);
            }

            updateTimestamp();
        } catch (err) {
            console.error('Refresh failed:', err);
            const errorHtml = `<div class="sara-error">Error cargando datos: ${err.message}<br><small>Ver consola (F12) para más detalles</small></div>`;
            document.querySelector('.sara-metrics-kpis').innerHTML = errorHtml;
        } finally {
            isRefreshing = false;
            if (btn) btn.disabled = false;
        }
    }

    // ── Bootstrap ───────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', () => {
        console.log('SARA Metrics Plus: DOM loaded');
        console.log('API_KEY:', API_KEY ? '***set***' : 'MISSING');
        console.log('AGENT_BASE:', AGENT_BASE);
        
        const btn = document.querySelector('.sara-refresh-btn');
        if (btn) btn.addEventListener('click', refresh);
        
        console.log('Starting initial refresh...');
        refresh().then(() => console.log('Initial refresh complete'))
                 .catch(e => console.error('Initial refresh failed:', e));
        
        setInterval(refresh, REFRESH_MS);
        console.log('Auto-refresh scheduled every', REFRESH_MS/1000, 'seconds');
    });
})();
