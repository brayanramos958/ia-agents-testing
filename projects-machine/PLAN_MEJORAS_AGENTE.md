# Plan de Mejoras: Agente de Aprendizaje

## Estado Actual del Sistema

### Backend
- **Framework**: Express.js con Groq SDK
- **Modelo por defecto**: llama-3.1-8b-instant
- **Parámetros actuales**: temperature: 0.7, max_tokens: 1024, top_p: 0.95
- **Memoria a corto plazo**: Últimos 20 intercambios
- **Memoria a largo plazo**: Hechos aprendidos y correcciones
- **Base de datos**: SQLite (aprendizajes, correcciones, conversaciones)

### Frontend
- **Framework**: React con Vite
- **API calls**: Servicio api.js con endpoints REST
- **Interfaz**: Chat con sistema de correcciones

### Problemas Identificados
1. **Sin validación de respuestas**: El LLM puede alucinar o salir del tema
2. **Temperatura fija**: 0.7 es moderadamente creativo, no ideal para precisión
3. **Extracción de hechos básica**: Solo usa regex simples
4. **Sin scoring de confianza**: No hay métricas de fiabilidad
5. **Tokens no expuestos**: El usage se obtiene pero no se muestra
6. **Sin constraints estrictos**: No hay mecanismo para forzar límites

---

## Plan de Implementación

### FASE 1: Mejoras de Precisión del Agente

#### 1.1 Servicio de Validación (Nuevo)
**Archivo**: `backend/src/services/validationService.js`
✅ **COMPLETADO**

#### 1.2 Parámetros Configurables
**Archivo**: `backend/src/routes/api.js`
✅ **COMPLETADO**

#### 1.3 Mejora del Prompt del Sistema
**Archivo**: `backend/src/services/memoryService.js`
✅ **COMPLETADO**

#### 1.4 Scoring de Confianza
**Archivo**: `backend/src/services/agentService.js`
✅ **COMPLETADO**

### FASE 2: Contador de Tokens API

#### 2.1 Endpoint de Tokens
**Archivo**: `backend/src/routes/api.js`
✅ **COMPLETADO**

#### 2.2 Modelo de Tokens
**Archivo**: `backend/src/models/tokenUsage.js` (nuevo)
✅ **COMPLETADO**

#### 2.3 Integración con Groq
**Archivo**: `backend/src/services/agentService.js`
✅ **COMPLETADO**

### FASE 3: Frontend - Mostrar Datos

#### 3.1 Componente de Tokens
**Archivo**: `frontend/src/components/TokenCounter.jsx` (nuevo)
✅ **COMPLETADO**

#### 3.2 Indicador de Confianza
**Archivo**: `frontend/src/components/ConfidenceBadge.jsx` (nuevo)
✅ **COMPLETADO**

#### 3.3 Modo Estricto Toggle
**Archivo**: `frontend/src/components/SettingsPanel.jsx` (nuevo)
✅ **COMPLETADO**

---

## Archivos Modificados

### Backend
| Archivo | Cambio | Estado |
|---------|--------|--------|
| `src/services/validationService.js` | **NUEVO** - Servicio de validación | ✅ |
| `src/services/agentService.js` | Añadir confidence score, parámetros dinámicos | ✅ |
| `src/services/memoryService.js` | Mejorar prompts, constraints | ✅ |
| `src/routes/api.js` | Nuevos endpoints de tokens | ✅ |
| `src/models/tokenUsage.js` | **NUEVO** - Modelo de uso de tokens | ✅ |
| `src/config/database.js` | Añadir tabla token_usage | ✅ |

### Frontend
| Archivo | Cambio | Estado |
|---------|--------|--------|
| `src/components/TokenCounter.jsx` | **NUEVO** - Componente de tokens | ✅ |
| `src/components/ConfidenceBadge.jsx` | **NUEVO** - Badge de confianza | ✅ |
| `src/components/SettingsPanel.jsx` | **NUEVO** - Panel de configuración | ✅ |
| `src/App.jsx` | Integrar nuevos componentes | ✅ |
| `src/services/api.js` | Funciones para tokens y parámetros | ✅ |
| `src/index.css` | Estilos para sidebar y nuevos elementos | ✅ |

---

## Características Implementadas

### 1. Modo Estricto
- Activa respuestas solo con información verificada
- Reduce temperatura a 0.3 para mayor precisión
- Validación más estricta de respuestas

### 2. Parámetros Configurables
- **Temperature**: Control de creatividad (0.0 - 1.0)
- **Max Tokens**: Límite de longitud de respuesta (256 - 4096)
- **Top P**: Control de diversidad (0.0 - 1.0)
- **Model**: Selección de modelo LLM

### 3. Sistema de Confianza
- Score de 0 a 1 basado en:
  - Coincidencia con hechos aprendidos
  - Consistencia con correcciones previas
  - Estructura de respuesta
  - Relevancia con la pregunta

### 4. Contador de Tokens API
- **GET /api/tokens** - Estadísticas generales
- **GET /api/tokens/session** - Sesión actual
- **GET /api/tokens/session/:id** - Sesión específica
- **GET /api/tokens/models** - Por modelo
- **GET /api/tokens/daily** - Uso diario
- **POST /api/tokens/reset** - Reiniciar contadores

### 5. Nuevos Endpoints
- **GET /models** - Modelos disponibles
- **POST /session/new** - Nueva sesión

---

## Notas Técnicas

### Límites Recomendados
- **Temperature**: 0.3 para modo estricto, 0.5-0.7 para creativo
- **Max tokens**: 512-2048 según necesidad
- **Umbral confianza**: 0.7 para usar hechos en modo estricto

### Almacenamiento de Tokens
- SQLite tabla `token_usage`
- Campos: id, session_id, model, prompt_tokens, completion_tokens, total_tokens, confidence_score, created_at

### Validación de Respuestas
1. Comparar respuesta con hechos de alta confianza (>70%)
2. Detectar contradicciones con correcciones previas
3. Penalizar respuestas fuera de tema
4. Retornar score entre 0 y 1

### Uso de la API
```javascript
// Ejemplo de uso con modo estricto
const response = await sendMessage(
  "¿Cuál es la capital de Francia?",
  "llama-3.1-8b-instant",
  {
    strictMode: true,
    temperature: 0.3,
    max_tokens: 512
  }
);

// Respuesta incluye:
// - response: Texto de la respuesta
// - confidence: Score de confianza (0-1)
// - validation: Detalles de validación
// - usage: Tokens utilizados
// - parameters: Parámetros usados
```

---

## Estado: ✅ IMPLEMENTACIÓN COMPLETADA
