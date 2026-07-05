"""
Agente IA v2 — construido con create_agent (harness oficial de LangChain 1.0)
Mismo contrato que agent.py: chat_con_agente(mensaje, session_id) -> str.

Diferencias con agent.py (loop manual):
- create_agent ejecuta el loop de tools por sí solo, en MULTIRONDA: el modelo
  puede llamar una tool, ver el resultado y decidir llamar otra (encadenamiento).
- El logging de tool calls se hace con middleware (@wrap_tool_call).
- Reusa sin cambios: tools/, model_config/, prompt/, conversation_history/.

Para usar esta versión, en el canal (main.py / main_chatwoot.py) cambia:
    from agent import chat_con_agente   →   from agent_v2 import chat_con_agente

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import sys
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# Directorio base del proyecto (portable para despliegue)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


# ============================================
# 0. CARGA DE CONFIGURACIÓN MODULAR (YAML)
# ============================================
def _cargar_yaml(ruta_relativa: str) -> dict:
    """Carga un archivo YAML relativo al directorio del proyecto."""
    ruta = os.path.join(BASE_DIR, ruta_relativa)
    with open(ruta, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


PROMPT_CONFIG = _cargar_yaml("prompt/prompt.yaml")
system_prompt = PROMPT_CONFIG["system_prompt"]

MODEL_CONFIG = _cargar_yaml("model_config/model_config.yaml")
_model_cfg = MODEL_CONFIG.get("model", {})
MODEL_NAME = _model_cfg.get("name", "gpt-4.1")
MODEL_TEMPERATURE = _model_cfg.get("temperature", 0.7)

from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import HumanMessage, AIMessage

# Importar tools desde la carpeta tools/ (sin cambios: plug and play)
from tools.Base_de_conocimiento import buscar_datapath
from tools.Busqueda_internet import buscar_internet
from tools.Hora_y_fecha import obtener_fecha_hora
from tools.google_sheets_departamentos_alquiler import buscar_departamentos_alquiler

# Histórico de conversación (PostgreSQL / Supabase), sin cambios
from conversation_history import crear_tabla_historial, get_session_history

# ============================================
# 1. LISTA DE TOOLS DISPONIBLES
# ============================================
tools = [
    buscar_datapath,                # Base de conocimiento Alpha State (RAG Qdrant)
    buscar_internet,                # Búsqueda en internet (Tavily)
    obtener_fecha_hora,             # Fecha y hora actual por zona horaria
    buscar_departamentos_alquiler,  # Departamentos en alquiler (Google Sheets)
]


# ============================================
# 2. MIDDLEWARE: LOG DE TOOL CALLS
# ============================================
@wrap_tool_call
def log_tool_calls(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage],
) -> ToolMessage:
    """Log de seguimiento: qué tool ejecuta el agente y con qué argumentos."""
    print(f"   🛠️  → {request.tool_call['name']}({request.tool_call['args']})")
    result = handler(request)
    contenido = getattr(result, "content", result)
    print(f"      ✔ {request.tool_call['name']} devolvió {len(str(contenido))} caracteres")
    return result


# ============================================
# 3. CONSTRUCCIÓN DEL AGENTE (create_agent)
# ============================================
# Instancia de modelo inicializada para conservar la temperature del YAML
chat = init_chat_model(MODEL_NAME, temperature=MODEL_TEMPERATURE)

# El system prompt (con fecha/hora) se inyecta por turno como primer mensaje,
# igual que en agent.py, así que aquí no se pasa system_prompt estático.
agente = create_agent(model=chat, tools=tools, middleware=[log_tool_calls])

# ============================================
# 4. CONTEXTO DE FECHA/HORA POR TURNO
# ============================================
AGENT_TIMEZONE = os.getenv("AGENT_TIMEZONE", MODEL_CONFIG.get("agent_timezone", "America/Lima"))


def _contexto_fecha_hora() -> str:
    """Fecha y hora actual para inyectar en el system prompt (cada turno)."""
    try:
        tz = ZoneInfo(AGENT_TIMEZONE)
    except Exception:
        tz = ZoneInfo("America/Lima")
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S") + f" (zona {AGENT_TIMEZONE})"


# ============================================
# 5. INICIALIZAR TABLA DE HISTORIAL
# ============================================
crear_tabla_historial()


# ============================================
# 6. FUNCIÓN DE CHAT — MISMO CONTRATO QUE agent.py
# ============================================
def chat_con_agente(mensaje_usuario: str, session_id: str) -> str:
    """
    Ejecuta el agente (create_agent) con tools y memoria.
    El harness maneja el loop de tools en multironda automáticamente.
    """
    # Obtener historial
    history = get_session_history(session_id)
    mensajes_previos = history.messages

    # Construir mensajes (inyectamos fecha/hora actual en cada turno)
    system_content = (
        system_prompt
        + "\n\n---\nFECHA Y HORA ACTUAL (referencia para este turno): "
        + _contexto_fecha_hora()
    )
    messages = [{"role": "system", "content": system_content}]

    for msg in mensajes_previos:
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            messages.append({"role": "assistant", "content": msg.content})

    messages.append({"role": "user", "content": mensaje_usuario})

    # Invocar el agente: create_agent ejecuta el loop LLM+tools completo
    result = agente.invoke({"messages": messages})
    respuesta_final = result["messages"][-1].content

    # Guardar en historial (mismo esquema que agent.py: user + assistant)
    history.add_user_message(mensaje_usuario)
    history.add_ai_message(respuesta_final)

    return respuesta_final


# Los canales viven fuera del orquestador (main.py / main_chatwoot.py).
if __name__ == "__main__":
    print("\nℹ️  agent_v2.py es el ORQUESTADOR (no se ejecuta directo).")
    print("   Para conversar por terminal:  AGENT_VERSION=2 python main.py")
    print("   Para el canal Chatwoot:       uvicorn main_chatwoot:app")
