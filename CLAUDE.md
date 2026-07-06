# Reglas del proyecto — Agente IA Multi-Tool (LangChain + Qdrant)

Las reglas viven en `.claude/rules/` y se importan aquí para que se carguen en cada sesión:

@.claude/rules/langchain-docs-first.md

---

# Especificación del proyecto (SDD — Spec Driven Development)

> Este bloque es la **especificación única y fuente de verdad** del proyecto. Está escrito
> para que cualquier persona (o agente) pueda **reconstruir el proyecto desde cero** sin
> leer el código existente. Si el código y esta spec divergen, se corrige la divergencia:
> la spec describe el comportamiento deseado; el código lo implementa.
>
> Metodología: primero se lee/actualiza la spec, luego se implementa contra ella, y por
> último se verifica contra los **criterios de aceptación** (§10). Todo cambio de
> comportamiento empieza editando esta spec.

## 1. Visión y alcance

**AlphaBot** es un agente conversacional de IA para **Alpha State Assessoria Imobiliária**
(inmobiliaria de Barão Geraldo, Campinas/SP, Brasil) que responde en español (o portugués
si el cliente lo usa) y decide autónomamente qué herramienta usar en cada turno. Combina:

- **RAG** sobre una base de conocimiento propia (Qdrant) — políticas de alquiler, boletos,
  multas y FAQ de Alpha State.
- **Inventario de inmuebles** en Google Sheets — departamentos disponibles para alquilar.
- **Pagos de inquilinos** en Google Sheets — desglose del pago mensual por departamento
  (agua, servicios básicos, gestión administrativa, mantenimientos, fondo de contingencia),
  con autenticación de dos factores (bloque inmobiliario + Responsable de Pago/Propietario)
  por ser información confidencial de cada inquilino.
- **Búsqueda en internet** en tiempo real (Tavily) — datos actuales (ej. índices IGPM/IPCA).
- **Fecha/hora** por zona horaria (stdlib, sin API).
- **Memoria persistente** por sesión en PostgreSQL/Supabase.

Se expone por dos **canales**: CLI interactivo (para pruebas/demo) y webhook **Chatwoot**
(para producción sobre WhatsApp/web widget). La lógica del agente es única y compartida.

**Fuera de alcance** (no implementar salvo pedido explícito): panel de administración,
autenticación de usuarios, streaming de tokens, multironda de tools (ver §5.4).
La ingesta/indexado a Qdrant se hace con el script `rag/rag.py` (ver §4): carga los
documentos de `rag/data/`, los trocea y los sube a la colección (creándola si no existe);
con `--reset` borra y recrea la colección (pide confirmación).

## 2. Requisitos funcionales

Cada requisito tiene un ID y un criterio de aceptación verificable (§10).

- **RF-01 (Router de tools):** dado un mensaje del usuario, el modelo decide sin intervención
  si responde directo o invoca una o varias tools. Saludos/charla → sin tools.
- **RF-02 (RAG Alpha State):** preguntas sobre políticas de alquiler, boletos, multas,
  contratos, documentación, reparaciones o datos de la inmobiliaria → tool `buscar_datapath`,
  que hace `similarity_search` (top-k=5) contra la colección Qdrant.
- **RF-03 (Internet):** preguntas sobre noticias, eventos o datos actuales no presentes en la
  base → tool `buscar_internet` (Tavily, máx. 5 resultados).
- **RF-04 (Fecha/hora):** preguntas sobre "qué hora/día es" u otra zona → tool
  `obtener_fecha_hora` (zona IANA opcional; por defecto `AGENT_TIMEZONE`). Además, la fecha/hora
  actual se **inyecta en el system prompt en cada turno** como contexto.
- **RF-12 (Departamentos en alquiler):** preguntas sobre departamentos disponibles para
  alquilar (disponibilidad, precios, ubicaciones, características) → tool
  `buscar_departamentos_alquiler`, que lee un Google Sheet vía service account (solo lectura)
  y acepta un filtro opcional de texto.
- **RF-13 (Pago mensual del inquilino):** preguntas sobre cuánto debe pagar un inquilino/
  propietario este mes o el desglose de su pago (agua, servicios básicos, gestión
  administrativa, mantenimientos preventivos, fondo de contingencia, redondeos, total) →
  tool `buscar_pago_inquilino`, que lee un Google Sheet vía el mismo service account
  (solo lectura). Es información **confidencial por fila**: la tool exige dos datos
  obligatorios — bloque inmobiliario y Responsable de Pago / Propietario — y solo responde
  si ambos coinciden exactamente con la misma fila (no es autenticación de usuarios de la
  app, sino autorización de datos por consulta; el "fuera de alcance" de §1 se refiere a
  login/sesiones de usuario).
- **RF-05 (Memoria persistente):** cada conversación se identifica por `session_id` (UUID). El
  historial (mensajes user+assistant) se persiste en PostgreSQL y se recarga en cada turno.
- **RF-06 (Continuidad de sesión):** en CLI, el usuario puede iniciar sesión nueva o continuar
  una existente pegando su UUID. En Chatwoot, el `session_id` se **deriva de forma estable** del
  `conversation_id` (`uuid5(NAMESPACE_DNS, "chatwoot-{id}")`), de modo que la misma conversación
  reusa siempre su historial.
- **RF-07 (Canal Chatwoot):** webhook `POST /webhook` que solo procesa eventos
  `message_created` de tipo `incoming`; responde con `message_type=outgoing` vía API de Chatwoot.
- **RF-08 (Handoff a humano):** si el mensaje contiene palabras clave (`humano`, `persona`,
  `asesor`, `agente`, `representante`, `hablar con alguien`) → reetiqueta la conversación a
  `atiende-humano`, responde un mensaje de transferencia y **no** invoca al agente.
- **RF-09 (Kill-switch IA):** si la conversación tiene la etiqueta `ia-off`, el agente **no**
  responde (permite que un humano tome el control).
- **RF-10 (Idioma y tono):** todas las respuestas en español, claras y amables.
- **RF-11 (Endpoints de operación):** `GET /` (info del servicio), `GET /health` (salud),
  `POST /test` (probar el agente sin Chatwoot: body `{message, session_id?}`).

## 3. Requisitos no funcionales

- **RNF-01 (Config desacoplada):** modelo y prompt viven en YAML, **no** en código. Secretos en
  `.env`. Cambiar prompt o modelo NO debe requerir tocar `.py`.
- **RNF-02 (Portabilidad de despliegue):** rutas resueltas contra `BASE_DIR =
  dirname(abspath(__file__))`; nunca rutas relativas al CWD. Toda config con `.get(clave, default)`.
- **RNF-03 (Fallo temprano):** cada módulo valida sus env obligatorias al importarse y lanza
  `ValueError` claro si faltan (DB, Qdrant, Tavily, Google Sheets).
- **RNF-04 (Robustez de tools):** las tools **capturan sus excepciones y devuelven un string**;
  nunca propagan errores al loop del agente.
- **RNF-05 (Modularidad):** se sigue la skill `langchain-modular-agent` (§4). El orquestador solo
  ensambla; los canales solo adaptan E/S; no se duplica lógica de agente.
- **RNF-06 (Docs-first):** antes de escribir/editar código LangChain se consulta la doc oficial
  vía MCP `docs-langchain` (regla importada arriba).
- **RNF-07 (Modelo por defecto):** `gpt-4.1` (skill `default-llm-model`); overrideable por YAML.
- **RNF-08 (Idempotencia de arranque):** `crear_tabla_historial()` es idempotente y segura de
  llamar en cada arranque.

## 4. Arquitectura y estructura de archivos

Convención modular (skill `langchain-modular-agent`): cada preocupación en su carpeta.

```
LangChain-AgenteIA-MultiTool-Qdrant/    # (nombre destino; renombrar carpeta desde ...-Pinecone)
├── model_config/
│   └── model_config.yaml            # name, temperature, agent_timezone
├── prompt/
│   └── prompt.yaml                  # system_prompt (bloque |); NO incluye fecha/hora
├── conversation_history/
│   ├── __init__.py                  # reexporta API pública del módulo
│   └── conversation_history.py      # conexión Postgres + crear_tabla + get_session_history
├── tools/
│   ├── __init__.py                  # importa las 5 tools y las lista en __all__
│   ├── Base_de_conocimiento.py      # @tool buscar_datapath  (RAG Qdrant — Alpha State)
│   ├── Busqueda_internet.py         # @tool buscar_internet  (Tavily)
│   ├── Hora_y_fecha.py              # @tool obtener_fecha_hora (stdlib)
│   ├── google_sheets_departamentos_alquiler.py  # @tool buscar_departamentos_alquiler (Google Sheets)
│   └── google_sheets_inquilinos_departamentos.py  # @tool buscar_pago_inquilino (Google Sheets, confidencial)
├── rag/
│   ├── rag.py                       # Script de ingesta a Qdrant (split + embeddings + upsert)
│   └── data/                        # Fuentes de la base de conocimiento (.md/.txt)
│       └── base_conocimiento_alpha_state.md
├── agent.py                         # ORQUESTADOR v1: loop manual (didáctico, 1 ronda de tools)
├── agent_v2.py                      # ORQUESTADOR v2: create_agent (multironda + middleware); mismo contrato
├── main.py                          # CANAL CLI (terminal); reusa chat_con_agente
├── main_chatwoot.py                 # CANAL webhook Chatwoot (FastAPI); reusa chat_con_agente
├── requirements.txt
├── .env                             # secretos (no versionar)
├── .env.example                     # plantilla de variables (sin valores; sí versionable)
└── CLAUDE.md                        # esta spec + reglas
```

**Flujo de datos (un turno):**
`canal → chat_con_agente(mensaje, session_id) → carga historial (Postgres) → arma messages
[system+fecha/hora, historial, user] → LLM.invoke → si tool_calls: ejecuta tools y 2ª invoke →
persiste user+assistant → devuelve string al canal.`

**Regla de ubicación:** ver tabla "¿dónde va cada cosa?" de la skill `langchain-modular-agent`.
Si algo que no es ensamblado "va en el orquestador", está mal ubicado.

## 5. Contratos de interfaces

### 5.1 Orquestador — `agent.py`
- `chat_con_agente(mensaje_usuario: str, session_id: str) -> str` — **API central**, reusada por
  todos los canales. Ejecuta el loop LLM+tools, loguea las tool calls y persiste el historial.
- Al importarse: carga YAMLs, construye `chat_con_tools = init_chat_model(...).bind_tools(tools)`
  y llama `crear_tabla_historial()`. **No contiene canales**: solo ensambla y expone la API.

### 5.1a Orquestador v2 — `agent_v2.py`
- Mismo contrato `chat_con_agente(mensaje, session_id) -> str`, implementado con
  `create_agent` de LangChain 1.0: el harness ejecuta el loop de tools en **multironda**
  (deroga la limitación de §5.4 para esta variante). Log de tool calls vía middleware
  `@wrap_tool_call`. Reusa tools/, YAMLs y conversation_history/ sin cambios.
- Los canales eligen versión cambiando un import:
  `from agent import chat_con_agente` ↔ `from agent_v2 import chat_con_agente`.

### 5.1b Canal CLI — `main.py`
- `main() -> None` — CLI interactivo con menú de sesión (nueva / continuar por UUID);
  solo adapta E/S de terminal. Selecciona orquestador con env `AGENT_VERSION`
  (default `1` = `agent.py`; `2` = `agent_v2.py`), ej. `AGENT_VERSION=2 python main.py`.
- `tools = [buscar_datapath, buscar_internet, obtener_fecha_hora, buscar_departamentos_alquiler, buscar_pago_inquilino]`
  (orden = registro).

### 5.2 Tools (`langchain_core.tools.@tool`)
El **docstring de cada tool es su contrato con el modelo** (define cuándo se invoca). Deben
incluir "Usa esta herramienta cuando…" y, si aplica, "NO uses…".
- `buscar_datapath(consulta: str) -> str` — RAG Qdrant (base de conocimiento Alpha State),
  `similarity_search(query, k=5)`, devuelve contexto formateado o mensaje de "no encontré".
  Conexión perezosa: valida env al importar, pero conecta a Qdrant en la primera búsqueda
  (permite arrancar el agente antes de la primera ingesta); si la colección no existe,
  indica ejecutar `python rag/rag.py`.
- `buscar_internet(consulta: str) -> str` — Tavily (`langchain_tavily.TavilySearch(max_results=5)`,
  con fallback a `langchain_community ... TavilySearchResults`), formatea título/contenido/URL.
- `obtener_fecha_hora(zona_horaria: str = "") -> str` — `zoneinfo`; zona vacía ⇒ `AGENT_TIMEZONE`;
  salida legible en español (día/mes) + ISO.
- `buscar_departamentos_alquiler(filtro: str = "") -> str` — Google Sheets vía `gspread` con
  service account (scope `spreadsheets.readonly`), cuya clave JSON completa se toma de la
  variable de entorno `GOOGLE_SHEETS_SERVICE_ACCOUNT_KEY` (`gspread.service_account_from_dict`,
  sin archivo en disco — así se puede definir como env var en el despliegue, ej. Easypanel);
  lee todas las filas con `get_all_records()` (fila 1 = cabecera), filtra por coincidencia de
  texto en cualquier columna si `filtro` no está vacío, y devuelve las filas formateadas o
  mensaje de "no encontré". Cliente perezoso: la clave JSON se parsea y valida al importar;
  la conexión se abre en la primera consulta.
- `buscar_pago_inquilino(bloque_inmobiliario: str, responsable_pago: str) -> str` — Google
  Sheets vía `gspread` con el mismo service account (`GOOGLE_SHEETS_SERVICE_ACCOUNT_KEY`),
  spreadsheet propio (`GOOGLE_SHEETS_INQUILINOS_SPREADSHEET_ID`, hoja
  `GOOGLE_SHEETS_INQUILINOS_WORKSHEET` default `"Hoja1"`). La hoja tiene cabecera en la
  **fila 2** (la fila 1 son encabezados de categoría que agrupan columnas), por lo que se
  leen los valores crudos (`get_all_values`) y se arman los registros a mano (columnas de
  la grilla sin nombre en la cabecera se descartan; `get_all_records` falla aquí porque
  las trata como cabeceras duplicadas vacías). **Ambos argumentos son obligatorios** (no hay valor
  por defecto): se normalizan (trim + casefold) y deben coincidir exactamente con las
  columnas `Bloque inmobiliario` y `Responsable de Pago / Propietario` de una misma fila;
  si no coinciden ambos, devuelve un mensaje de "no encontré" sin indicar cuál dato falló
  (evita filtrar si el bloque o el nombre es el incorrecto). Si coincide, formatea todas
  las columnas no vacías de la fila (consumo de agua, servicios básicos, gestión
  administrativa, mantenimientos preventivos, gastos varios, fondo de contingencia,
  redondeos y total). Cliente perezoso, igual patrón que `buscar_departamentos_alquiler`.

### 5.3 Memoria — `conversation_history/`
- `crear_tabla_historial() -> None` — crea la tabla si no existe (idempotente).
- `get_session_history(session_id: str) -> PostgresChatMessageHistory` — historial de la sesión.
- Reexporta también `DATABASE_URL` y `TABLE_NAME` (env `DB_TABLE_NAME`, default `"chat_history"`).

### 5.4 Loop de tools (comportamiento exacto)
1ª `invoke` con `messages`. Si `response.tool_calls`: se **append** la `response`, se ejecuta cada
tool casada por `name`, se **append** un `ToolMessage(content=<resultado>, tool_call_id=<id>)` por
cada una, y una **2ª `invoke`** produce la respuesta final. Sin tool_calls → `response.content`.
Es **una sola ronda** (2 llamadas máx). Multironda queda fuera de alcance (§1); si se requiere,
envolver en `while response.tool_calls:` con tope de iteraciones.

### 5.5 Canal Chatwoot — `main_chatwoot.py` (FastAPI)
- `POST /webhook` — orquesta RF-07/08/09; deriva `session_id` con `conversation_id_to_uuid`.
- `send_chatwoot_message(conversation_id, message) -> bool`,
  `update_chatwoot_labels(conversation_id, labels) -> bool`,
  `conversation_id_to_uuid(conversation_id) -> str`.
- `GET /` , `GET /health`, `POST /test` (RF-11). Servidor: `uvicorn`, host `0.0.0.0`, puerto `8000`.

## 6. Modelo de datos

Tabla **`chat_history`** en PostgreSQL, gestionada por
`langchain_postgres.PostgresChatMessageHistory` (esquema creado por su
`create_tables`). Clave lógica: `session_id` (UUID) agrupa los mensajes de una conversación;
cada fila es un mensaje (rol + contenido) en orden. No se define esquema manual: se delega a
la librería. El backend recomendado es **Supabase** (PostgreSQL gestionado).

## 7. Configuración

### `model_config/model_config.yaml`
```yaml
model:
  name: gpt-4.1
  temperature: 0.7
agent_timezone: America/Lima   # overrideable por env AGENT_TIMEZONE
```

### `prompt/prompt.yaml`
Solo `system_prompt` como bloque `|`, estructurado en tags XML según la skill
`agent-prompt-yaml-format` (`<rol>`, `<contexto_temporal>`, `<herramientas>`,
`<instrucciones>`, `<reglas>`, `<ejemplos>`). Debe: definir persona (AlphaBot de Alpha
State), listar las 5 tools y cuándo usar cada una, exigir español (portugués si el cliente
lo usa), y referir a la FECHA/HORA inyectada en runtime (**no** escribir fecha/hora fija
aquí). No duplicar contenido de la base de conocimiento. Debe instruir explícitamente que
`buscar_pago_inquilino` requiere pedir bloque inmobiliario y Responsable de Pago/Propietario
antes de invocarla, y que nunca se comparten montos de otro departamento.

## 8. Variables de entorno (`.env`)

| Variable | Obligatoria | Uso |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | LLM (gpt-4.1) + embeddings (`text-embedding-ada-002`) |
| `QDRANT_URL` | ✅ | URL de la instancia Qdrant (Easypanel/DigitalOcean) |
| `QDRANT_API_KEY` | ✅ | API key del cliente (mismo valor que `QDRANT__SERVICE__API_KEY` del servidor) |
| `QDRANT_COLLECTION` | ➖ (default `alpha-state-conocimiento`) | Colección Qdrant de la base de conocimiento |
| `TAVILY_API_KEY` | ✅ | Búsqueda en internet |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | ✅ | ID del Google Sheet de departamentos (entre `/d/` y `/edit` de la URL) |
| `GOOGLE_SHEETS_SERVICE_ACCOUNT_KEY` | ✅ | Contenido JSON completo de la clave del service account (no una ruta a archivo; permite configurarla como env var en el despliegue, ej. Easypanel) |
| `GOOGLE_SHEETS_WORKSHEET` | ➖ (default: primera hoja) | Nombre de la pestaña/hoja a leer |
| `GOOGLE_SHEETS_INQUILINOS_SPREADSHEET_ID` | ✅ | ID del Google Sheet de pagos de inquilinos (entre `/d/` y `/edit` de la URL); usa el mismo `GOOGLE_SHEETS_SERVICE_ACCOUNT_KEY` |
| `GOOGLE_SHEETS_INQUILINOS_WORKSHEET` | ➖ (default `Hoja1`) | Nombre de la pestaña/hoja de pagos a leer |
| `DB_USER`, `DB_PASSWORD`, `DB_HOST` | ✅ | PostgreSQL/Supabase (historial) |
| `DB_PORT` | ➖ (default `5432`) | Puerto Postgres |
| `DB_NAME` | ➖ (default `postgres`) | Base de datos |
| `DB_TABLE_NAME` | ➖ (default `chat_history`) | Tabla del historial de conversación |
| `AGENT_VERSION` | ➖ (default `1`) | Orquestador del CLI: `1` = agent.py, `2` = agent_v2.py |
| `AGENT_TIMEZONE` | ➖ (default `America/Lima`) | Zona horaria del agente |
| `CHATWOOT_BASE_URL`, `CHATWOOT_ACCOUNT_ID`, `CHATWOOT_API_ACCESS_TOKEN` | Solo canal Chatwoot | API de Chatwoot |
| `CHATWOOT_BOT_LABEL` | ➖ (default `atiende-ia`) | Etiqueta de handoff |

> `.env` contiene secretos: **no** versionar. El password se codifica con `quote_plus` al armar la URL.
> La etiqueta `ia-off` es un literal en código (kill-switch), no una env var.

## 9. Dependencias y stack

Python 3.11+ (por `zoneinfo`). Paquetes clave (ver `requirements.txt`):
`langchain>=1.0`, `langchain-openai`, `langchain-community`, `langchain-qdrant`, `qdrant-client`,
`langchain-postgres`, `psycopg[binary]`, `langchain-tavily` (+`tavily-python`), `gspread`,
`fastapi`, `uvicorn`, `requests`, `python-dotenv`, `PyYAML`.
Externos: cuenta OpenAI, instancia **Qdrant** (Easypanel/DigitalOcean, poblada con `rag/rag.py`),
cuenta **Tavily**, **PostgreSQL/Supabase**, un **Google Sheet** de departamentos compartido con
el service account (API de Google Sheets habilitada), y (opcional) instancia **Chatwoot**.

## 10. Procedimiento de replicación desde cero

1. **Estructura:** crear carpetas de §4 y archivos `__init__.py` (`tools/`, `conversation_history/`).
2. **Entorno:** `python -m venv .venv && source .venv/bin/activate`; crear `requirements.txt` (§9) y `pip install -r requirements.txt`.
3. **Secretos:** crear `.env` con las variables de §8.
4. **Config:** escribir `model_config/model_config.yaml` y `prompt/prompt.yaml` (§7).
5. **Memoria:** implementar `conversation_history/` (§5.3) con validación de env y `quote_plus`.
6. **Tools:** implementar las 5 tools (§5.2), cada una con docstring rica, carga de env y manejo de errores; registrarlas en `tools/__init__.py`.
7. **Orquestador:** implementar `agent.py` (§5.1, §5.4): carga YAML, `bind_tools`, `chat_con_agente`, inyección de fecha/hora por turno.
8. **Canales:** implementar `main.py` (CLI, §5.1b) y `main_chatwoot.py` (§5.5), ambos reusando `chat_con_agente`.
9. **Datos (ingesta):** colocar las fuentes de la base de conocimiento en `rag/data/` y ejecutar `python rag/rag.py` (o `--reset` para vaciar el índice primero). Los embeddings deben ser `text-embedding-ada-002` (mismo modelo que la tool RAG).

## 11. Criterios de aceptación (verificación)

- **CA-01:** `python main.py` arranca, muestra las tools y
  el `session_id`, y responde en español.
- **CA-02:** "¿Qué incluye mi boleto de alquiler?" invoca `buscar_datapath` (RF-02).
- **CA-03:** "¿Qué pasó hoy en las noticias?" invoca `buscar_internet` (RF-03).
- **CA-04:** "¿Qué hora es en Madrid?" invoca `obtener_fecha_hora` con zona `Europe/Madrid` (RF-04).
- **CA-05:** "Hola" responde directo, sin tools (RF-01).
- **CA-06:** al continuar una sesión por UUID, el agente recuerda el contexto previo (RF-05/06).
- **CA-07:** `uvicorn main_chatwoot:app` levanta; `GET /health` → `healthy`; `POST /test`
  `{"message":"hola"}` devuelve respuesta.
- **CA-08:** webhook con `message_type != incoming` o etiqueta `ia-off` → `status: ignored` (RF-07/09).
- **CA-09:** mensaje con "quiero hablar con un humano" → reetiqueta `atiende-humano` y no llama al agente (RF-08).
- **CA-10:** faltando una env obligatoria (DB/Qdrant/Tavily/Google Sheets), el proceso falla al importar con `ValueError` claro (RNF-03).
- **CA-11:** "¿Qué departamentos tienen para alquilar?" invoca `buscar_departamentos_alquiler` y responde con los datos del Google Sheet (RF-12).
- **CA-12:** "¿Cuánto tengo que pagar este mes?" sin dar bloque/responsable → el agente los
  pide antes de invocar la tool; dando ambos correctos, invoca `buscar_pago_inquilino` y
  responde con el desglose (RF-13). Con un bloque o responsable incorrecto (o de otro
  inquilino), la tool no devuelve datos de pago de nadie (RF-13).
