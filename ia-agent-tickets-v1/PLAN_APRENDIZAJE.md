# Plan de Implementación: Aprendizaje del Agente (RAG para Tickets)

## 📌 Objetivo
Dotar al agente de IA con memoria semántica para que "aprenda" de tickets resueltos anteriormente. Esto permitirá que el agente no espere a que el resolutor le pida ayuda (como lo hace actualmente), sino que:
1. **Prevenga la creación de tickets**: Dándole soluciones automáticas al `creador` si el problema ya fue resuelto antes.
2. **Asista activamente al resolutor**: Sugiriendo resoluciones instantáneas cuando le asignan un ticket nuevo.

## 🛠️ Estado Actual vs Deseado
*   **Actual**: La herramienta `buscar_soluciones_similares` hace una búsqueda de texto simple en la base de datos SQL del backend de Node (`LIKE %...%`) y el agente solo lo sugiere a los resolutores si ellos preguntan activamente o se traban decribiendo un problema.
*   **Deseado**: Búsqueda Semántica con Vector Embeddings usando LangChain (RAG - *Retrieval-Augmented Generation*) en Python, con proactividad tanto para creadores como resolutores.

---

## 📋 Pasos Necesarios para la Implementación

### Fase 1: Motor de Búsqueda Semántica (Vector Store)
Actualmente, el backend realiza búsquedas exactas/de texto. El agente en Python es ideal para manejar IA Semántica y similitudes reales.
1. **Instalar dependencias en Python**: Instalar `chromadb` (base de datos vectorial empotrada) y `langchain-huggingface` (para generar embeddings locales rápidos sin costo) en la carpeta `agent/`.
2. **Crear script de Ingesta Inicial**: Crear un código en Python que, al inicio de la app o mediante un endpoint, recupere el historial de todos los tickets cerrados desde tu base de datos SQLite y los convierta en vectores (embeddings) dentro de ChromaDB.
3. **Actualizar la tool `buscar_soluciones_similares`**: Modificar esta herramienta en `agent/tools.py` para que ya no haga la petición `GET` al backend de Node, sino que consulte la base vectorial local de ChromaDB. Retornará los top tickets más relevantes puramente por el **significado semántico** del problema, no solo por coincidencia de palabras.

### Fase 2: Proactividad hacia el Creador (Deflexión de Tickets)
Modificar el flujo del LangGraph para que el Agente trate de resolver el problema del usuario sin siquiera crear el ticket en la BD para soporte.
1. **Actualizar el `CREADOR_PROMPT`** (`agent/prompts.py`):
   *   *Nuevo comportamiento*: Justo después de que el usuario describe su problema y **antes** de confirmar la creación del ticket, el agente debe disparar automáticamente la herramienta `buscar_soluciones_similares`.
   *   *Respuesta del Agente*: "He encontrado que alguien tuvo este mismo problema recientemente y la solución fue: [solución]. ¿Esto resuelve tu duda o prefieres que de igual forma genere el ticket de soporte?"

### Fase 3: Auto-Asistencia al Resolutor
Dotar a los técnicos de soporte con respuestas antes de que las pidan.
1. **Actualizar el `RESOLUTOR_PROMPT`** (`agent/prompts.py`):
   *   *Nuevo comportamiento*: Cuando el resolutor pida ver los detalles de un ticket que se le acaba de asignar (`get_ticket_detail`), el agente, por voluntad propia, consultará el historial y le sugerirá: "Noto que este ticket sobre X se parece al Ticket #123 que se resolvió reiniciando el caché de la app principal. Quizá aplicando esa misma solución lo resuelvas."

### Fase 4: Retroalimentación y Aprendizaje Continuo (Tiempo real)
El agente debe aprender inmediatamente después de resolver un ticket, sin tener que reiniciar.
1. **Sincronización Webhook al Cerrar Ticket**: Cuando el resolutor marque un ticket como exitosamente resuelto a través del agente (herramienta `resolve_ticket`), el Python no solo informará a la API de Node. Inmediatamente agregará la tupla "(Descripción original, Resolución aplicada)" a la base de datos de vectores ChromaDB. 
   *   *Resultado*: El ticket cerrado estará disponible a los 2 segundos como una posible solución para futuros usuarios.

## 📦 Recomendaciones Técnicas
Para mantener la simpleza de tu arquitectura actual, recomiendo evitar colocar una base de datos vectorial externa. ChromaDB trabaja como un archivo local (similar a SQLite) perfecto para este caso de uso y encaja directo con tu entorno Langchain actual en el microservicio Python.
