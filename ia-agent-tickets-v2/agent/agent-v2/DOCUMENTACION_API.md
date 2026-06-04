# Documentación API de Helpdesk (`its_helpdesk_api`)

## Resumen

La API de Mesa de Ayuda (Helpdesk) proporciona endpoints RESTful permitiendo a sistemas externos o scripts conectar y recuperar información de tickets (listado y detalle) creados por el propio usuario. Utiliza autenticación sin estado (stateless) mediante headers HTTP.

---

## URL Base

```
http://tu-instancia-odoo.com/helpdesk/api/v1
```

---

## Autenticación

Todos los endpoints usan una arquitectura RESTful sin estado (`auth='none'`) y validan las credenciales vía HTTP Headers en **todas** las peticiones:

| Header | Descripción |
|---|---|
| `X-Odoo-Db` | Nombre de la base de datos |
| `X-Odoo-Login` | Correo electrónico o login del usuario |
| `X-Api-Key` | Contraseña o **Clave API** del usuario |
| `Accept` | `application/json` |

---

## Endpoints Disponibles

### 1. Verificar Autenticación
**`GET /helpdesk/api/v1/authenticate`**

Valida si las credenciales en los Headers son correctas.

**Respuesta exitosa:**
```json
{
  "status": "success",
  "result": "authenticated",
  "uid": 17,
  "company_id": 1
}
```

---

### 2. Listar Tickets
**`GET /helpdesk/api/v1/tickets`**

Obtiene el listado general de tickets del Helpdesk (requiere autenticación válida).

**Parámetros de consulta (Query Params):**
| Parámetro | Tipo | Descripción |
|---|---|---|
| `name` | Cadena | Opcional. Buscar un ticket por su número de referencia (Ej. SR-0000020). |
| `stage_id` | Entero | Opcional. Filtrar por ID de la etapa. |
| `limit` | Entero | Máximo de registros (por defecto: 80) |
| `offset` | Entero | Desplazamiento para paginación |

**Respuesta exitosa:**
```json
{
  "status": "success",
  "count": 2,
  "data": [
    {
      "id": 105,
      "name": "INC-000105",
      "asunto": "No enciende el equipo",
      "stage_id": 1,
      "stage_name": "Nuevo",
      "create_date": "2024-03-31T09:00:00",
      "priority_id": 2,
      "priority_name": "Alta"
    }
  ]
}
```

---

### 3. Obtener Detalle de Ticket
**`GET /helpdesk/api/v1/ticket/{id}`**

Obtiene información estructurada y ampliada de un registro de helpdesk de tu propiedad, incluyendo el historial de comunicación (hilo del chatter).

**Respuesta exitosa:**
```json
{
  "status": "success",
  "data": {
    "id": 105,
    "name": "INC-000105",
    "asunto": "No enciende el equipo",
    "descripcion": "<p>Tengo un problema, cuando presiono el bot&oacute;n, hace un pitido.</p>",
    "stage_id": 1,
    "stage_name": "Nuevo",
    "priority_id": 2,
    "priority_name": "Alta",
    "category_id": 4,
    "category_name": "Hardware",
    "subcategory_id": 12,
    "subcategory_name": "Computadoras",
    "asignado_a_id": 8,
    "asignado_a_name": "Agente Soporte ITS",
    "create_date": "2024-03-31T09:00:00",
    "messages": [
      {
         "id": 4432,
         "author_name": "Agente Soporte ITS",
         "body": "<p>Estamos revisando el incidente.</p>",
         "date": "2024-03-31 09:15:20"
      }
    ]
  }
}
```

---

### 4. Crear Ticket
**`POST /helpdesk/api/v1/ticket/create`**

Crea un nuevo ticket de soporte asociado al usuario autenticado. 
El cuerpo de la petición (JSON) debe incluir parámetros obligatorios de asunto y descripción.

**Payload de Envío (Body JSON):**
```json
{
  "asunto": "Problema con la VPN remota",
  "descripcion": "Desde la actualización de hoy no me puedo conectar a la VPN Cisco AnyConnect.",
  "category_id": 4,
  "priority_id": 1
}
```
* **`asunto`**: (String, Requerido) Título del ticket.
* **`descripcion`**: (String, Requerido) Detalle del caso.
* **`category_id`**: (Integer, Opcional) ID numérico de la categoría.
* **`priority_id`**: (Integer, Opcional) Numérico (Ej: 1=Baja, 2=Alta).

**Respuesta exitosa (`201 Created`):**
```json
{
  "status": "success",
  "message": "Ticket creado exitosamente",
  "data": {
    "id": 108,
    "name": "INC-000108",
    "asunto": "Problema con la VPN remota"
  }
}
```

---

## Ejemplo de Uso (Python)

```python
import requests

headers = {
    "X-Odoo-Db": "base_datos",
    "X-Odoo-Login": "usuario@correo.com",
    "X-Api-Key": "tu_clave_api",
    "Accept": "application/json"
}

# Obtener los tickets propios:
res = requests.get("http://bms.com/helpdesk/api/v1/tickets", headers=headers)

if res.status_code == 200:
    for ticket in res.json().get('data', []):
        print(f"[{ticket['name']}] Asunto: {ticket['asunto']} | Etapa: {ticket['stage_name']}")
```
