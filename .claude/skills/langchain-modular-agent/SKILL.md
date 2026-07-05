---
name: langchain-modular-agent
description: Convención modular concreta para agentes LangChain multi-tool con RAG (vector store como Qdrant o Pinecone), historial persistente (PostgreSQL/Supabase) y config en YAML. Define dónde vive y cómo se configura el conversation_history, el model_config, el prompt y las tools, más cómo el orquestador ensambla todo (init_chat_model + bind_tools + loop de tool_calls). Úsala al crear un nuevo agente LangChain de este tipo, refactorizar uno monolítico, agregar/mover una tool, o decidir dónde va cada pieza. Aplica este layout por defecto salvo que el usuario diga lo contrario.
---

# LangChain Modular Agent (multi-tool + RAG + memoria persistente)

Convención concreta para agentes construidos con **LangChain** (`init_chat_model` + `bind_tools`, sin `AgentExecutor`) que combinan:

- **Tools** (RAG con un vector store — Qdrant en este proyecto —, búsqueda en internet con Tavily, utilidades locales)
- **Historial persistente** en PostgreSQL/Supabase (`PostgresChatMessageHistory`)
- **Configuración desacoltada del código** en archivos YAML (modelo y prompt)

Cada preocupación vive en su propia carpeta. El orquestador (`agente_*.py`) solo ensambla; los canales (`main_chatwoot.py`, CLI) solo adaptan la entrada/salida.

> Antes de escribir o modificar código LangChain, consulta la skill `langchain-docs-first`. Para elegir el modelo LLM, aplica `default-llm-model`.

## Layout estándar

```
<project-root>/
├── model_config/
│   └── model_config.yaml          ← parámetros del LLM (name, temperature) + agent_timezone
├── prompt/
│   └── prompt.yaml                ← system_prompt (la fecha/hora se inyecta en runtime, NO aquí)
├── conversation_history/
│   ├── __init__.py                ← reexporta la API pública del módulo
│   └── conversation_history.py    ← conexión Postgres + crear_tabla_historial + get_session_history
├── tools/
│   ├── __init__.py                ← importa y lista todas las tools en __all__
│   ├── Base_de_conocimiento.py    ← @tool de RAG contra el vector store (Qdrant)
│   ├── Busqueda_internet.py       ← @tool buscar_internet (Tavily)
│   └── Hora_y_fecha.py            ← @tool obtener_fecha_hora (stdlib, sin API)
├── agente_*.py                    ← ORQUESTADOR: carga YAML, bind_tools, loop de tool_calls
├── main_chatwoot.py               ← ENTRYPOINT de canal (webhook), reusa chat_con_agente
├── requirements.txt
└── .env                           ← secretos: OPENAI/QDRANT/TAVILY keys, DB_*
```

## Regla mental: ¿dónde va cada cosa?

| Si cambio… | → vive en |
|---|---|
| Modelo LLM (name) o temperature | `model_config/model_config.yaml` |
| Zona horaria por defecto del agente | `model_config/model_config.yaml` (`agent_timezone`) o env `AGENT_TIMEZONE` |
| Prompt / persona / instrucciones del agente | `prompt/prompt.yaml` |
| Backend o tabla de memoria | `conversation_history/conversation_history.py` |
| Agregar / modificar una herramienta | archivo nuevo en `tools/` + registrarla en `tools/__init__.py` |
| Cómo se ensamblan las piezas / loop de tools | `agente_*.py` (orquestador) |
| Nuevo canal (Chatwoot, Telegram, API, CLI) | entrypoint propio que reusa `chat_con_agente` |

Si la respuesta natural es "el orquestador" para algo que no sea ensamblar → **algo está mal**. El orquestador solo cambia por orquestación.

## Carga de configuración modular (en el orquestador)

Un solo helper lee YAML relativo a `BASE_DIR` (portable para despliegue):

```python
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _cargar_yaml(ruta_relativa: str) -> dict:
    with open(os.path.join(BASE_DIR, ruta_relativa), "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

# Prompt
system_prompt = _cargar_yaml("prompt/prompt.yaml")["system_prompt"]

# Modelo
MODEL_CONFIG = _cargar_yaml("model_config/model_config.yaml")
_m = MODEL_CONFIG.get("model", {})
MODEL_NAME = _m.get("name", "gpt-4.1")
MODEL_TEMPERATURE = _m.get("temperature", 0.7)
```

Siempre usa `.get(..., default)` para que falte una clave no rompa el arranque.

## `model_config/model_config.yaml`

Configuración **pura** del modelo. Sin código, sin prompt.

```yaml
model:
  name: gpt-4.1          # default del proyecto (ver skill default-llm-model)
  temperature: 0.7
agent_timezone: America/Lima   # overrideable con env AGENT_TIMEZONE
```

## `prompt/prompt.yaml`

Solo el `system_prompt` como bloque `|`. La fecha/hora **no** se escribe aquí: se inyecta en cada turno desde el código. El prompt debe listar las tools disponibles y cuándo usar cada una.

```yaml
system_prompt: |
  Eres DataBot, un asistente de IA de DATAPATH...
  HERRAMIENTAS DISPONIBLES:
  1. buscar_datapath: ...
  2. buscar_internet: ...
  INSTRUCCIONES: ...
```

## `conversation_history/`

Memoria persistente con `langchain_postgres.PostgresChatMessageHistory` sobre PostgreSQL/Supabase. La API pública son dos funciones:

- `crear_tabla_historial()` — idempotente, se llama una vez al arrancar.
- `get_session_history(session_id) -> PostgresChatMessageHistory` — historial por sesión.

Puntos clave del módulo:
- Credenciales desde env (`DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`); valida que existan al importar.
- `quote_plus(DB_PASSWORD)` al construir el `DATABASE_URL` (passwords con caracteres especiales).
- `TABLE_NAME = "chat_history"` centralizado.
- `__init__.py` reexporta `crear_tabla_historial`, `get_session_history`, `DATABASE_URL`, `TABLE_NAME`.

El `session_id` es un UUID: nuevo por conversación, o reusado para continuar una sesión.

## `tools/`

Cada tool es un archivo con una función decorada `@tool` (de `langchain_core.tools`). Reglas:

1. **Un archivo por tool** (o por familia de tools relacionada).
2. **Docstring rica**: el docstring ES lo que el modelo lee para decidir cuándo llamarla. Incluye "Usa esta herramienta cuando…", y cuando aplique "NO uses esta herramienta para…".
3. **Args tipados** con descripción.
4. Cada tool carga su propia config/env (`load_dotenv`, API keys) y **falla temprano** si falta una key.
5. Devuelven **strings ya formateados** para el modelo, y capturan sus errores devolviendo un string (no lanzan hacia el loop).
6. **Registrar** la tool en `tools/__init__.py` (import + `__all__`).

```python
from langchain_core.tools import tool

@tool
def buscar_datapath(consulta: str) -> str:
    """Busca información sobre DATAPATH en la base de conocimientos.
    Usa esta herramienta cuando el usuario pregunte sobre programas, cursos,
    docentes, precios o modalidades de DATAPATH.

    Args:
        consulta: La pregunta o tema a buscar
    """
    ...
    return resultado_formateado
```

## Orquestador (`agente_*.py`): ensamblado y loop de tools

Patrón manual con `bind_tools` (sin `AgentExecutor`):

```python
tools = [buscar_datapath, buscar_internet, obtener_fecha_hora]
chat = init_chat_model(MODEL_NAME, temperature=MODEL_TEMPERATURE)
chat_con_tools = chat.bind_tools(tools)
crear_tabla_historial()

def chat_con_agente(mensaje_usuario: str, session_id: str) -> str:
    history = get_session_history(session_id)

    # system prompt + fecha/hora inyectada este turno
    system_content = system_prompt + "\n\n---\nFECHA Y HORA ACTUAL: " + _contexto_fecha_hora()
    messages = [{"role": "system", "content": system_content}]
    for msg in history.messages:
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            messages.append({"role": "assistant", "content": msg.content})
    messages.append({"role": "user", "content": mensaje_usuario})

    response = chat_con_tools.invoke(messages)          # 1ª llamada

    if response.tool_calls:                             # ejecutar tools
        messages.append(response)
        for tc in response.tool_calls:
            t = next(t for t in tools if t.name == tc["name"])
            messages.append(ToolMessage(content=t.invoke(tc["args"]),
                                        tool_call_id=tc["id"]))
        respuesta_final = chat_con_tools.invoke(messages).content   # 2ª llamada
    else:
        respuesta_final = response.content

    history.add_user_message(mensaje_usuario)
    history.add_ai_message(respuesta_final)
    return respuesta_final
```

Notas:
- La **fecha/hora se inyecta en el system prompt cada turno** (no vive en el YAML). Para otras zonas, el modelo usa la tool `obtener_fecha_hora`.
- El historial se persiste **después** de generar la respuesta (user + assistant).
- Este patrón hace **una ronda** de tools (2 llamadas). Si necesitas multi-ronda, envuelve la parte de `tool_calls` en un `while response.tool_calls:` con un tope de iteraciones.

## Entrypoints / canales

Cada canal es un archivo separado que **reusa `chat_con_agente(mensaje, session_id)`** y solo adapta entrada/salida:
- CLI: `main()` con `input()` y menú de sesión (nueva / continuar por UUID).
- Chatwoot/webhook: `main_chatwoot.py` mapea el contacto/conversación a un `session_id`.

Nunca dupliques la lógica del agente en el canal; importa y llama.

## Al agregar una tool nueva (checklist)

1. Crear `tools/<Nombre>.py` con `@tool`, docstring rica, carga de env y manejo de errores.
2. Importarla y añadirla a `__all__` en `tools/__init__.py`.
3. Añadirla a la lista `tools = [...]` del orquestador.
4. Describirla en `prompt/prompt.yaml` (qué hace y cuándo usarla).
5. Añadir su API key a `.env` y a `requirements.txt` el paquete necesario.
