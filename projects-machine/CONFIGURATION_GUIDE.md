# Guía de Configuración del Agente de Aprendizaje

Este documento describe los archivos clave para configurar los aspectos más importantes del agente de aprendizaje.

## 🔑 Credenciales y Configuración del Servidor

| Aspecto | Archivo | Ubicación específica | Comentario |
|---------|---------|----------------------|------------|
| **Groq API Key** | `backend/.env` | `GROQ_API_KEY=tu_clave_aqui` | Obtener en https://console.groq.com/ |
| **Puerto del Servidor** | `backend/.env` | `PORT=3001` | Puerto donde escucha el backend |
| **Entorno Node** | `package.json` (backend) | `"type": "module"` | Necesario para usar ES modules |

## ⚙️ Parametrización del Modelo LLM

| Aspecto | Archivo | Ubicación específica | Comentario |
|---------|---------|----------------------|------------|
| **Modelo Predeterminado** | `backend/src/services/agentService.js` | En `initGroqClient()` y `sendMessage()` | Modelo por defecto: `llama-3.1-8b-instant` |
| **Temperature** | `backend/src/routes/api.js` | En endpoint `/api/chat` (línea ~43) | Valor por defecto: 0.7 |
| **Max Tokens** | `backend/src/routes/api.js` | En endpoint `/api/chat` (línea ~43) | Valor por defecto: 1024 |
| **Top P** | `backend/src/routes/api.js` | En endpoint `/api/chat` (línea ~44) | Valor por defecto: 0.95 |
| **Parámetros Configurables vía API** | `backend/src/routes/api.js` | Endpoints `/models`, `/session/new` | Permiten cambiar parámetros dinámicamente |

## 📊 Configuración de Seguimiento de Tokens

| Aspecto | Archivo | Ubicación específica | Comentario |
|---------|---------|----------------------|------------|
| **Esquema de Tabla Token Usage** | `backend/src/config/database.js` | Función `createTables()` (líneas 65-78) | Define columnas: id, session_id, model, prompt_tokens, etc. |
| **Registro de Uso de Tokens** | `backend/src/models/tokenUsage.js` | Función `recordTokenUsage()` (líneas 25-50) | Guarda cada llamada al LLM con sus métricas |
| **Obtención de Estadísticas** | `backend/src/models/tokenUsage.js` | Funciones `getTotalTokenUsage()`, `getTokenUsageByModel()`, etc. | Consultas para reportes |
| **Endpoints API de Tokens** | `backend/src/routes/api.js` | Sección "Token usage endpoints" (líneas 154-230) | `/tokens`, `/tokens/session`, `/tokens/models`, etc. |
| **Integración con Groq** | `backend/src/services/agentService.js` | En `sendMessage()` (líneas ~80-120) | Extrae `usage` de la respuesta de Groq y lo registra |

## ✅ Sistema de Validación y Confianza

| Aspecto | Archivo | Ubicación específica | Comentario |
|---------|---------|----------------------|------------|
| **Lógica de Validación** | `backend/src/services/validationService.js` | Función `validateResponse()` | Compara respuesta con hechos aprendidos |
| **Scoring de Confianza** | `backend/src/services/agentService.js` | En `sendMessage()` después de validación | Combina múltiples factores (0-1) |
| **Constraints de Prompt** | `backend/src/services/memoryService.js` | Función `getSystemPrompt()` | Instrucciones para modo estricto/creativo |
| **Umbral de Confianza** | `PLAN_MEJORAS_AGENTE.md` | Sección "Límites Recomendados" | 0.7 para usar hechos en modo estricto |

## 🧠 Configuración de Memoria y Aprendizaje

| Aspecto | Archivo | Ubicación específica | Comentario |
|---------|---------|----------------------|------------|
| **Hechos Aprendidos** | `backend/src/config/database.js` | Tabla `learned_facts` (líneas 54-63) | Incluye `confidence_score` y `times_confirmed` |
| **Correcciones de Usuario** | `backend/src/config/database.js` | Tabla `corrections` (líneas 41-51) | Historial de correcciones para aprendizaje |
| **Extracción de Hechos** | `backend/src/services/memoryService.js` | Función `extractFactsFromText()` | Mejorada con regex y NLP básico |
| **Decaimiento de Confianza** | `backend/src/models/learnedFacts.js` | (Si existiera) - actualmente en `learned_facts` table | Lógica para reducir confianza con el tiempo |

## 🖥️ Configuración del Frontend

| Aspecto | Archivo | Ubicación específica | Comentario |
|---------|---------|----------------------|------------|
| **URL Base del API** | `frontend/src/services/api.js` | Constante `API_BASE_URL` | Por defecto: `http://localhost:3001/api` |
| **Funciones de Tokens** | `frontend/src/services/api.js` | `getTokenStats()`, `getSessionTokenUsage()`, etc. | Llamadas a endpoints de tokens |
| **Mostrar Contador de Tokens** | `frontend/src/components/TokenCounter.jsx` | Componento principal | Formatea y muestra datos de tokens |
| **Indicador de Confianza** | `frontend/src/components/ConfidenceBadge.jsx` | Propiedad `confidence` (0-1) | Cambia color según umbrales (verde >0.7) |
| **Panel de Configuración** | `frontend/src/components/SettingsPanel.jsx` | Sliders para temperature, max_tokens, etc. | Envía cambios al backend vía API |
| **Modo Estricto Toggle** | `frontend/src/components/SettingsPanel.jsx` | Switch que ajusta parámetros | Activa validación estricta y baja temperature |

## 📐 Límites y Valores Recomendados

Según el documento `PLAN_MEJORAS_AGENTE.md`:

| Parámetro | Valor Recomendado | Contexto |
|-----------|-------------------|----------|
| **Temperature (Modo Estricto)** | 0.3 | Máxima precisión |
| **Temperature (Modo Creativo)** | 0.5-0.7 | Balance creatividad/precisión |
| **Max Tokens** | 512-2048 | Según complejidad de tarea |
| **Umbral de Confianza** | 0.7 | Para usar hechos en modo estricto |
| **Historial Conversacional** | Últimos 20 intercambios | Memoria a corto plazo |

## 🛠️ Cómo Modificar Configuraciones

### Para cambiar el modelo por defecto:
1. Editar `backend/src/services/agentService.js`
2. Buscar donde se inicializa el modelo en `sendMessage()`
3. Cambiar `"llama-3.1-8b-instant"` por otro modelo disponible en Groq

### Para ajustar límites de parámetros:
1. Editar `frontend/src/components/SettingsPanel.jsx`
2. Modificar los rangos de los sliders (min/max/step)
3. Actualizar las etiquetas mostradas al usuario

### Para cambiar el umbral de confianza:
1. Editar `backend/src/services/validationService.js`
2. Ajustar la lógica en `calculateConfidenceScore()`
3. O modificar el umbral usado en `agentService.js` para activar modo estricto

### Para cambiar qué se guarda en token usage:
1. Editar `backend/src/models/tokenUsage.js`
2. Modificar la función `recordTokenUsage()` para incluir/excluir campos
3. Actualizar las funciones de consulta si se añaden/quitan columnas

## 📝 Notas Importantes

1. **Reinicio requerido**: Algunos cambios (como puerto o API key) requieren reiniciar el backend
2. **Base de datos**: Cambios en el esquema de token usage requieren migrar o reinicializar la base de datos
3. **Validación frontend**: Los rangos en `SettingsPanel.jsx` deben coincidir con los límites aceptados por el backend
4. **Documentación**: Siempre actualizar este guía cuando se hagan cambios significativos en la configuración

---
*Guía generada basada en el análisis del códigobase y el plan de mejoras implementado*