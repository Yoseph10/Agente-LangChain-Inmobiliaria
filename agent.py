"""
Agente IA Completo: Base de Conocimiento + Internet + Histórico
- Tool 1: Base de Conocimiento (RAG con Qdrant)
- Tool 2: Búsqueda en Internet (Tavily)
- Histórico: Guarda conversaciones en PostgreSQL

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# Directorio base del proyecto (portable para despliegue)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Agregar el directorio actual al path para importar tools
sys.path.insert(0, BASE_DIR)


# ============================================
# 0. CARGA DE CONFIGURACIÓN MODULAR (YAML)
# ============================================
def _cargar_yaml(ruta_relativa: str) -> dict:
    """Carga un archivo YAML relativo al directorio del proyecto."""
    ruta = os.path.join(BASE_DIR, ruta_relativa)
    with open(ruta, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# Prompt del agente
PROMPT_CONFIG = _cargar_yaml("prompt/prompt.yaml")
system_prompt = PROMPT_CONFIG["system_prompt"]

# Configuración del modelo
MODEL_CONFIG = _cargar_yaml("model_config/model_config.yaml")
_model_cfg = MODEL_CONFIG.get("model", {})
MODEL_NAME = _model_cfg.get("name", "gpt-4.1")
MODEL_TEMPERATURE = _model_cfg.get("temperature", 0.7)

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

# Importar tools desde la carpeta tools/
from tools.Base_de_conocimiento import buscar_datapath
from tools.Busqueda_internet import buscar_internet
from tools.Hora_y_fecha import obtener_fecha_hora
from tools.google_sheets_departamentos_alquiler import buscar_departamentos_alquiler

# Histórico de conversación (PostgreSQL / Supabase) desde el módulo modular
from conversation_history import crear_tabla_historial, get_session_history

# ============================================
# 1. LISTA DE TOOLS DISPONIBLES
# ============================================
tools = [
    buscar_datapath,                # Base de conocimiento DATAPATH
    buscar_internet,                # Búsqueda en internet (Tavily)
    obtener_fecha_hora,             # Fecha y hora actual por zona horaria
    buscar_departamentos_alquiler,  # Departamentos en alquiler (Google Sheets)
]

# ============================================
# 2. CONFIGURACIÓN DEL MODELO CON TOOLS
# ============================================
chat = init_chat_model(MODEL_NAME, temperature=MODEL_TEMPERATURE)
chat_con_tools = chat.bind_tools(tools)

# ============================================
# 3. PROMPT DEL AGENTE + CONTEXTO FECHA/HORA
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


# El system_prompt se carga desde prompt/prompt.yaml (ver bloque 0).

# ============================================
# 4. INICIALIZAR TABLA DE HISTORIAL
# ============================================
# La conexión y funciones de histórico viven en conversation_history/
crear_tabla_historial()

# ============================================
# 5. FUNCIÓN DE CHAT CON AGENTE + TOOLS
# ============================================
def chat_con_agente(mensaje_usuario: str, session_id: str) -> str:
    """
    Ejecuta el agente con tools y memoria.
    El agente decide si usar herramientas o responder directamente.
    """
    # Obtener historial
    history = get_session_history(session_id)
    mensajes_previos = history.messages
    
    # Construir mensajes para el modelo (inyectamos fecha/hora actual en cada turno)
    system_content = (
        system_prompt
        + "\n\n---\nFECHA Y HORA ACTUAL (referencia para este turno): "
        + _contexto_fecha_hora()
    )
    messages = [{"role": "system", "content": system_content}]
    
    # Agregar historial
    for msg in mensajes_previos:
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            messages.append({"role": "assistant", "content": msg.content})
    
    # Agregar mensaje actual
    messages.append({"role": "user", "content": mensaje_usuario})
    
    # Invocar modelo con tools
    response = chat_con_tools.invoke(messages)
    
    # Procesar tool calls si existen
    if response.tool_calls:
        # Log de seguimiento: qué tools decidió usar el agente y con qué argumentos
        print(f"   🛠️  El agente decidió usar {len(response.tool_calls)} tool(s):")
        for tool_call in response.tool_calls:
            print(f"      → {tool_call['name']}({tool_call['args']})")

        # Ejecutar cada tool
        tool_results = []
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            # Buscar y ejecutar la tool
            for t in tools:
                if t.name == tool_name:
                    result = t.invoke(tool_args)
                    print(f"      ✔ {tool_name} devolvió {len(str(result))} caracteres")
                    tool_results.append({
                        "tool_call_id": tool_call["id"],
                        "result": result
                    })
                    break
        
        # Agregar respuesta del modelo con tool calls y resultados
        messages.append(response)
        for tr in tool_results:
            messages.append(ToolMessage(
                content=tr["result"],
                tool_call_id=tr["tool_call_id"]
            ))
        
        # Segunda llamada para obtener respuesta final
        final_response = chat_con_tools.invoke(messages)
        respuesta_final = final_response.content
    else:
        # Sin tool calls, respuesta directa
        print("   💬 Respuesta directa (sin tools)")
        respuesta_final = response.content
    
    # Guardar en historial
    history.add_user_message(mensaje_usuario)
    history.add_ai_message(respuesta_final)
    
    return respuesta_final


# Los canales viven fuera del orquestador:
#   - CLI (terminal):  main.py
#   - Chatwoot (web):  main_chatwoot.py
# Ambos importan chat_con_agente desde este módulo.
if __name__ == "__main__":
    print("\nℹ️  agent.py es el ORQUESTADOR (no se ejecuta directo).")
    print("   Para conversar por terminal:  python main.py")
    print("   Para el canal Chatwoot:       uvicorn main_chatwoot:app")
