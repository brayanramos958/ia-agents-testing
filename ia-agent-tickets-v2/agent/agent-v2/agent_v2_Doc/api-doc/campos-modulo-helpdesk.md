# Campos del Modelo de Ticket

## Descripción de Campos

| Nombre Técnico | Nombre para mostrar | Descripción del campo |
| :--- | :--- | :--- |
| `name` | Número de ticket | Secuencia alfanumérica única que identifica al ticket en el sistema. |
| `asunto` | Asunto | Título o descripción breve del incidente o requerimiento reportado. |
| `inicio_falla` | Fecha inicio de atención caso | Registra el momento exacto en el que comenzó a presentarse el incidente. |
| `fin_falla` | Fecha fin de atención caso | Registra el momento en el que se confirmó la resolución o fin de la atención. |
| `descripcion` | Descripción | Detalle extenso y completo del problema, solicitud o requerimiento. |
| `causa_raiz` | Causa raíz | Explicación del motivo fundamental o técnico que originó el incidente. |
| `partner_id` | Solicitante | Contacto asociado al cliente o empleado que levanta el ticket. |
| `motivo_resolucion` | Motivo de resolución | Detalle técnico o funcional de la solución aplicada para resolver el ticket. |
| `fecha_creacion` | Fecha de creación | Almacena automáticamente la fecha y hora en que se registró el ticket. |
| `fecha_cierre` | Fecha de cierre | Marca de tiempo que registra cuándo el ticket fue pasado a un estado final (cerrado). |
| `creado_por` | Creado por | Referencia al usuario del sistema que generó el registro del ticket. |
| `company_id` | Compañía | Empresa u organización a la que pertenece o se factura el ticket. |
| `ultima_modificacion` | Última modificación | Marca de tiempo que registra la última actualización que sufrió el registro. |
| `actualizado_por` | Actualizado por | Usuario del sistema que realizó la última modificación en el ticket. |
| `asignado_a` | Agente asignado | Especialista, técnico o agente responsable de la resolución del ticket. |
| `agent_group_id` | Grupo de agentes | Equipo o nivel de soporte técnico al que está escalado el ticket. |
| `stage_id` | Estado | Etapa actual del flujo de trabajo (workflow) en la que se encuentra el ticket. |
| `ticket_type_id` | Tipo de Caso | Clasifica la naturaleza del ticket (Ej. Incidente, Requerimiento, Cambio). |
| `usuario_solicitante_id` | Usuario solicitante | Usuario interno del sistema vinculado a la persona que realizó la petición. |
| `category_id` | Categoría (Nivel 1) | Clasificación principal para categorizar el área de impacto del ticket. |
| `subcategory_id` | Subcategoría (Nivel 2) | Clasificación de segundo nivel para especificar aún más el tipo de problema. |
| `element_id` | Elemento (Nivel 3) | Identifica el elemento, sistema o hardware específico afectado. |
| `priority_id` | Prioridad | Nivel de prioridad asignado al ticket basado en la matriz de impacto/urgencia. |
| `urgency_id` | Urgencia | Nivel de rapidez esperada para resolver el ticket según la necesidad del negocio. |
| `impact_id` | Impacto | Grado de afectación que tiene el incidente sobre la operación del negocio. |
| `sla_id` | SLA aplicable | Acuerdo de Nivel de Servicio (SLA) asignado para medir los tiempos de cumplimiento. |
| `deadline_date` | Fecha límite SLA | Fecha máxima estimada para la resolución total del ticket sin infringir el SLA. |
| `deadline_n1_date` | Fecha límite N1 | Tiempo máximo permitido para la respuesta inicial o resolución del primer nivel. |
| `deadline_n2_date` | Fecha límite N2 | Tiempo máximo permitido para escalar o resolver por parte del segundo nivel. |
| `is_about_to_expire` | Próximo a vencer | Indicador booleano que señala si el ticket está a punto de incumplir su meta de SLA. |
| `sla_status` | Estado SLA | Estado actual del cumplimiento del SLA (Ej. En tiempo, En riesgo, Vencido). |
| `origin_id` | Origen | Canal o medio por el cual el ticket fue reportado (Portal, Teléfono, Email). |
| `schedule_id` | Horario Laboral | Calendario de trabajo asociado para calcular correctamente los tiempos hábiles. |
| `last_reply_by` | Última respuesta | Identifica quién realizó el último comentario (cliente, gestor o sistema). |
| `last_staff_reply_date` | Fecha última respuesta gestor | Registra la marca de tiempo de la última comunicación enviada por un agente. |
| `last_customer_reply_date` | Fecha última respuesta cliente | Registra la marca de tiempo de la última comunicación enviada por el solicitante. |
| `reminder_count` | Contador de recordatorios | Número de notificaciones automatizadas enviadas alertando sobre tiempos. |
| `payroll_country_id` | País de Nómina | Identificador de la ubicación o país aplicable para reglas de nómina u operativas. |
| `is_outside_schedule` | Fuera de horario laboral | Indicador lógico si el ticket fue creado o está activo fuera de la franja operativa. |
| `log_ids` | Registros de Auditoría | Historial que almacena cronológicamente los cambios de estado y acciones (Log). |
| `timeline_html` | Línea de Tiempo | Presentación en formato visual HTML del ciclo de vida y eventos del ticket. |
| `date_last_paused` | Última Pausa | Momento en el cual el cronómetro del SLA del ticket fue puesto en pausa. |
| `total_paused_time` | Tiempo Total Pausado (horas) | Acumulado de horas en el que el ticket ha estado suspendido esperando un tercero. |
| `is_paused` | Está Pausado | Checkbox que indica que el tiempo de gestión del ticket se encuentra actualmente detenido. |
| `sla_notified_50` | Notificado SLA 50% | Verificación interna de que se ha enviado la alerta que el tiempo al 50% ha pasado. |
| `sla_notified_70` | Notificado SLA 70% | Verificación interna de alerta para avance del SLA al 70%. |
| `sla_notified_90` | Notificado SLA 90% | Verificación interna de escalamiento o alerta crítica (90% del tiempo de resolución). |
| `sla_expired_notified` | Notificado SLA Expirado | Verificación de envío de alerta cuando la vigencia del SLA se ha incumplido. |
| `group_users_display` | Agentes del grupo | Campo visual que ayuda a revisar todos los integrantes capacitados para tomar el ticket. |
| `available_agent_ids` | Agentes disponibles | Agentes del sistema que se encuentran habilitados en el grupo para atención. |
| `is_assigned_to_me` | Está asignado a mí | Evalúa dinámicamente si el ticket está asignado al usuario actual en sesión. |
| `is_stage_closed` | Etapa de Cierre | Flag condicional que señala si la etapa en la que está asignado el ticket equivale a cerrado. |
| `is_resolve_stage` | Etapa de Resolución | Flag que identifica si el ticket ya se considera 'resuelto' antes de cerrarlo definitivamente. |
| `suggested_knowledge_ids` | Artículos sugeridos | Enlaces a la base de conocimiento que pueden ayudar al agente a responder rápidamente. |
| `has_suggestions` | Tiene Sugerencias | Indica si el motor del sistema ha detectado algún artículo de soporte recomendado. |
| `suggested_knowledge_html` | Sugerencias (HTML) | Renderización nativa en vista de los artículos sugeridos al técnico. |
| `satisfaction_rating` | Satisfacción | Calificación o métrica cualitativa de qué tan satisfecho quedó el cliente tras el cierre del ticket. |
| `satisfaction_rating_num` | Calificación (Num) | Equivalente numérico (score) del indicador de satisfacción general recibido. |
| `satisfaction_comment` | Comentario de Mejora | Retroalimentación en texto libre que el solicitante deja acerca de la atención. |
| `satisfaction_date` | Fecha de Respuesta | Momento exacto en el cual el solicitante completó la encuesta. |
| `satisfaction_complete` | Encuesta Completada | Valida si el cliente finalizó su cuestionario completo tras cerrar el ticket. |
| `ticket_id` | Ticket | Llave foránea para vincular logs de operaciones (auditoría/aprobaciones) a una matriz principal. |
| `author_id` | Autor | Identificador de quién originó una operación paralela en las líneas/logs (comentarios u otro). |
| `content` | Contenido | Cuerpo principal de un registro de texto anexo, como un log descriptivo o comentario. |
| `attachment_ids` | Adjuntos | Mapeo de archivos binarios, fotos y documentos técnicos ligados al caso. |
| `approver_id` | Aprobador / Aprobador Principal | Usuario jerárquico o técnico responsable de conceder un permiso en una fase solicitada. |
| `role` | Rol/Área | Función del aprobador dentro de la organización (Ej. Finanzas, Seguridad). |
| `status` | Estado | Valor dinámico que indica si una línea o ticket está en progreso, evaluándose o finalizado. |
| `approval_status` | Estado de Aprobación | Resumen general si la necesidad operativa dependiente está Autorizada/Rechazada/Pendiente. |
| `approval_date` | Fecha Aprobación/Rechazo | Momento cronológico exacto de confirmación del dictamen sobre la solicitud de aprobación. |
| `comment` | Comentario/Justificación | Razonamiento sobre el cual un proceso dependiente de confirmación fue aprobado o negado. |
| `affected_user_id` | Usuario Afectado | Persona dentro de la organización que realmente sufre la falla o por quien se levanta el servicio. |
| `viewer_ids` | Observadores (Viewers) | Usuarios o Seguidores CC que tienen visibilidad sin rol primario de ejecución u operatividad. |
| `approval_line_ids` | Líneas de Aprobación | Estructura de modelo en vista de árbol, donde van mapeados los saltos multi-escala del permiso. |
| `is_approver` | Es el Aprobador | Verifica lógicamente si el usuario activo con la sesión tiene facultades para gestionar un status. |
| `x_new_private_note` | Nueva Nota Privada | Caja de texto temporal para almacenar anotaciones técnicas del Gestor sólo visibles internamente. |
| `x_private_note_ids` | Historial Notas Privadas | Modelo relacional para recopilar el log o la cronología oculta de gestión paralela al usuario final. |
| `fecha_asignacion` | Fecha de Asignación | El primer momento exacto en el que al ticket se le declara un agente de seguimiento primario. |
| `mttn_min` | MTTN (Min) | Mean Time To Notify; Indicador KPI estadístico para visualizar el retardo de confirmación del suceso. |
| `mttr_hrs` | MTTR (Hrs) | Mean Time To Resolve; Indicador estadístico que valida cuántas horas transcurrieron a la solución de la meta. |
| `resolucion_nivel` | Nivel de Resolución | Metadato para identificar si el N1, N2 o superiores completaron de raíz el evento asignado a la cola. |
| `requester_type` | Tipo de Solicitante | Categoría analítica sobre la cuenta dueña (Ej. Interna, Directivo, VIP). |
| `employee_id` | Empleado Solicitante | Vínculo foráneo cruzado con la tabla de Recursos Humanos (`hr.employee`) por si es el creador. |
| `system_equipment` | Equipo relacionado | Nombre comercial de la herramienta, dispositivo o software donde se suscitó el síntoma del reporte. |
| `affected_user_name` | Nombre usuario afectado | Valor en formato texto libre si la persona perjudicada no se encasilla dentro de nuestro modelo de datos nativo. |
| `contact_info` | Información de contacto | Metrajes genéricos (Télefonos anexos, Emails extra) para agilizar tiempos sin necesidad del CRM Base. |
| `anydesk_id` | ID de AnyDesk | Código serial único si la intervención amerita un canal de acceso remoto no presencial. |
| `availability_datetime` | Disponibilidad | Ventana de intervalo que propuso el cliente para poder recibir llamadas de solución a su horario local. |
| `affected_users_count` | Número usuarios afectados | Volumen contabilizado de empleados impactados, vital para promover urgencias a desastres mayores. |
| `manager_id` | Jefatura | Responsable divisional del área a la que pertenece quién levanta el boleto de atención en el portal. |
| `department` | Departamento | Categoría organizativa madre a la que se ancla el solicitante derivado a analíticas posteriores de costes. |
| `project` | Proyecto | Área de presupuesto o despliegue en la cual un ticket generará horas base o sobrecargo laboral justificado. |
| `sla_scheduled_date_50` | Prog. 50% | Fecha futura predicha para cuando se ejecutará el 50% del cumplimiento esperado según la cuota SLA. |
| `sla_scheduled_date_70` | Prog. 70% | Fecha futura predicha al equivalente del 70% de atención sobre la caducidad del SLA. |
| `sla_scheduled_date_90` | Prog. 90% | Fecha escalación de gravedad predictiva donde las alarmas a mandos medios deberían figurar en su Dashboard. |
| `sla_group_n1_id` | Grupo Responsable N1 | Colectivo funcional inicialmente responsabilizado con la toma del incidente genérico. |
| `sla_group_n2_id` | Grupo Responsable N2 | Colectivo avanzado o de escalación encargado por si la incidencia excede la experiencia N1. |
| `is_admin_user` | Es Administrador | Criterio de verificación para desenmascarar botones de purga o permisos altos en jerarquías del portal. |
| `sla_time_n1_display` | Tiempo N1 | Texto numérico calculado onthefly con el SLA activo que dice en horas lo asignado al Tier Inicial. |
| `sla_time_n2_display` | Tiempo N2 | Restante numérico o temporal proyectado en horas para el colectivo de salto (Tier 2). |

---

## Modelo: Niveles de Servicio y SLA (helpdesk_sla.py)

| Nombre Técnico | Nombre para mostrar | Descripción del campo |
| :--- | :--- | :--- |
| `name` | Nombre del SLA | Título del acuerdo de nivel de servicio. |
| `category_id` | Categoría | Vinculación del tiempo SLA a la categoría principal del nivel 1. |
| `subcategory_id` | Subcategoría | Vinculación del tiempo SLA a la subcategoría nivel 2. |
| `element_id` | Elemento | Vinculación del tiempo SLA al elemento específico nivel 3. |
| `priority_id` | Prioridad | Prioridad que detona las condiciones del SLA. |
| `time_amount` | Tiempo Objetivo | Cantidad numérica de tiempo para la resolución general. |
| `time_unit` | Unidad de Tiempo | Especifica la unidad del objetivo (minutos, horas, días). |
| `time_n1_amount` | Tiempo Solución N1 | Cuota de SLA exclusiva para el grupo de soporte inicial (Tier 1). |
| `time_n1_unit` | Unidad de Tiempo N1 | Unidad de tiempo para la regla del primer nivel. |
| `time_n2_amount` | Tiempo Adicional N2 | Tiempo complementario si el ticket escala al segundo nivel. |
| `time_n2_unit` | Unidad de Tiempo N2 | Unidad de tiempo para el escalamiento N2. |
| `group_n1_id` | Grupo Responsable N1 | Equipo técnico que deberá cumplir la meta N1. |
| `group_n2_id` | Grupo Responsable N2 | Equipo técnico que deberá cumplir la meta N2. |
| `active` | Activo | Booleano para archivar reglas SLA antiguas. |
| `description` | Descripción | Explicación funcional detallada del dictamen o política de servicio. |

---

## Modelo: Categorías del Sistema (helpdesk_category.py)

| Nombre Técnico | Nombre para mostrar | Descripción del campo |
| :--- | :--- | :--- |
| `name` | Nombre de Categoría | Etiqueta principal que ve el usuario al seleccionar su problemática. |
| `level_selection` | Nivel de Categoría | Enumera si es un nivel 1 (Categoría), nivel 2 (Subcategoría) o nivel 3 (Elemento). |
| `parent_id` | Categoría Padre | Relación jerárquica para anclar un subnivel al árbol de su elemento mayor. |
| `child_ids` | Subcategorías Hijas | Relación inversa para extraer todos los subniveles dependientes. |
| `level` | Nivel | Valor numérico posicional del nivel de profundidad en el árbol. |
| `full_name` | Nombre Completo | Ruta concatenada descriptiva (Ej. Hardware / Impresoras / Tóner). |
| `ticket_count` | Cantidad de Tickets | Campo calculado con el volumen histórico de incidencias de esa clase. |

---

## Modelos: Calificadores (Impacto, Urgencia, Prioridad, Origen y Tipos)

| Nombre Técnico | Nombre para mostrar | Descripción del campo |
| :--- | :--- | :--- |
| `color` | Color | Valor hexadecimal para diferenciar gráficamente las etiquetas (Aplica en varios modelos). |
| `sequence` | Secuencia | Orden en el que se renderea el listado desplegable en la interfaz. |
| `name` (urgency) | Nombre de Urgencia | Qué tan rápido el negocio exige una contención (Alta, Media, Baja). |
| `name` (impact) | Nombre de Impacto | Volumen o gravedad operativa (Ej. Afecta sitio, Afecta empleado). |
| `name` (priority) | Nombre de Prioridad | Resultado del cruce matriz entre urgencia e impacto. |
| `name` (origin) | Nombre del Origen | Canal de procedencia del reporte (Portal, Correo, Teléfono). |
| `name` (type) | Nombre del Tipo | Naturaleza del servicio a prestar (Incidente, Tarea, Requerimiento). |
| `description` | Descripción | Detalles anexos sobre el accionar de cada tipificador. |

---

## Modelo: Estados y Workflows (helpdesk_ticket_stage.py)

| Nombre Técnico | Nombre para mostrar | Descripción del campo |
| :--- | :--- | :--- |
| `name` | Nombre del Estado | Etiqueta (Ej. Nuevo, En Progreso, Resuelto, Cerrado). |
| `is_start` | Estado Inicial | Bandera lógica de la fase donde inician y nacen todos los registros. |
| `is_folded` | Plegado en Kanban | Regla UI de Odoo para ocultar visualmente la columna. |
| `is_close` | Estado de Cierre | Flag definitorio para que el SLA y reloj del ticket se detenga totalmente. |
| `is_resolve` | Estado de Resolución | Flag para pre-cierres que requieren confirmación posterior del cliente. |
| `is_pause` | Estado de Pausa | Detiene el conteo temporal del motor de SLA (Esperando Terceros o Proveedor). |
| `is_reply_client_stage` | Etapa al responder solicitante | Autocambio de etapa cuando llega un mail de contestación del cliente. |
| `is_reply_staff_stage` | Etapa al responder staff | Autocambio de etapa cuando el agente gestor envía respuesta. |

---

## Modelo: Administración Operativa (Horarios, Grupos y RRHH)

### helpdesk_agent_group.py

| Nombre Técnico | Nombre para mostrar | Descripción del campo |
| :--- | :--- | :--- |
| `name` | Nombre del Grupo | Título al Escuadrón / Célula de soporte. |
| `agent_ids` | Agentes | Empleados relacionados bajo el perfil para atender casos derivados. |
| `supervisor_id` | Supervisor | Jefatura o Team Lead evaluador técnico del grupo de gestión. |
| `agent_count` | Número de Agentes | Conteo estadístico o limitante operativo del tamaño funcional. |

### helpdesk_schedule.py & helpdesk_schedule_holiday.py

| Nombre Técnico | Nombre para mostrar | Descripción del campo |
| :--- | :--- | :--- |
| `timezone` | Timezone | Ubicación horaria (TZ) utilizada para emparejar SLAs con relojes locales. |
| `is_24_7` | 24 horas al día / 7 días | Marca el calendario base como perpetuo si no aplican las bandas de hora estándar. |
| `monday_from` / `monday_to` (etc) | Desde / Hasta (por día) | Franjas operativas habilitadas para contabilizar los minutos de SLA permitidos. |
| `total_weekly_hours` | Total Horas Semanales | Acumulación matemática del calendario para análisis de disponibilidad. |
| `holiday_ids` | Días Festivos | Fechas nacionales o asuetos (date y name) donde el cálculo se frena. |
| `payroll_country_ids` | Países de Nómina | Vinculación del calendario a un país por diferencias de leyes. |

---

## Configuraciones Generales (res_config_settings.py / helpdesk_knowledge.py)

| Nombre Técnico | Nombre para mostrar | Descripción del campo |
| :--- | :--- | :--- |
| `helpdesk_sequence_prefix` | Prefijo de Tickets | Estructura en cadena alfanumérica que antecede los folios (Ej: TCK-). |
| `helpdesk_sequence_padding` | Dígitos de Secuencia | Cantidad de ceros numéricos secuenciales en los folios (Ej. 0001). |
| `helpdesk_notify_on_*` | Notificadores de Sistema | Flags condicionales para habilitar correos automáticos al Asignar, Crear o Cambiar de fase el ticket. |
| `helpdesk_auto_close_day` | Días para Cierre Automático | Threshold de días por inactividad antes de archivar crónicamente un caso. |
| `helpdesk_email_from` | Correo Remitente | Cuenta global y alias configurado de las alertas salientes y entrantes. |
| `body` (knowledge) | Contenido | Documentación de manuales HTML embebidos en el portal de base de conocimiento. |
| `keywords` | Palabras Clave | Diccionario utilizado algorítmicamente para autovincular tickets con artículos de auto-ayuda. |

## Estadísticas

- **Total de campos**: 150 campos documentados (94 del modelo de Ticket + 14 del modelo de SLA + 7 del modelo de Categorías + 8 de Calificadores + 8 de Estados/Workflows + 12 de Administración Operativa + 7 de Configuraciones Generales)
- **Campos técnicos**: Todos con nombre técnico en formato snake_case
- **Descripciones**: Cada campo incluye una descripción detallada en español
