"""
Integración del Agente IA con Chatwoot
Webhook para recibir mensajes y responder automáticamente.

Autor: Ing. Kevin Inofuente Colque - DataPath
"""

import os
import sys
import uuid
import requests
from dotenv import load_dotenv, find_dotenv
from fastapi import FastAPI, Request
import uvicorn

# Cargar variables de entorno
load_dotenv(find_dotenv())

# Agregar el directorio actual al path (portable para despliegue)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Importar directamente el agente (sin rutas locales)
from agent import chat_con_agente

print("🤖 Cargando Agente (Qdrant)...")
print("✅ Agente cargado correctamente")

# ============================================
# CONFIGURACIÓN DE CHATWOOT
# ============================================
CHATWOOT_BASE_URL = os.getenv("CHATWOOT_BASE_URL")
CHATWOOT_ACCOUNT_ID = os.getenv("CHATWOOT_ACCOUNT_ID")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_ACCESS_TOKEN")

# Etiqueta que activa el bot (opcional, para handoff)
BOT_LABEL = os.getenv("CHATWOOT_BOT_LABEL", "atiende-ia")
# Etiqueta que desactiva la IA: si el usuario/conversación tiene "ia-off", el agente NO responde
TAG_IA_OFF = "ia-off"

if not all([CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID, CHATWOOT_API_TOKEN]):
    print("⚠️  ADVERTENCIA: Faltan variables de Chatwoot en .env")
    print("   Requeridas: CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID, CHATWOOT_API_ACCESS_TOKEN")
else:
    print(f"✅ Chatwoot configurado: {CHATWOOT_BASE_URL}")

# ============================================
# FUNCIONES DE CHATWOOT
# ============================================
def send_chatwoot_message(conversation_id: int, message: str) -> bool:
    """
    Envía un mensaje de respuesta a una conversación en Chatwoot.
    
    Args:
        conversation_id: ID de la conversación
        message: Mensaje a enviar
    
    Returns:
        True si se envió correctamente, False si hubo error
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/messages"
    headers = {
        'api_access_token': CHATWOOT_API_TOKEN,
        'Content-Type': 'application/json'
    }
    payload = {
        'content': message,
        'message_type': 'outgoing'
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        print(f"   ✅ Mensaje enviado a conversación {conversation_id}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Error al enviar mensaje: {e}")
        return False


def update_chatwoot_labels(conversation_id: int, labels: list) -> bool:
    """
    Actualiza las etiquetas de una conversación en Chatwoot.
    
    Args:
        conversation_id: ID de la conversación
        labels: Lista de etiquetas
    
    Returns:
        True si se actualizó correctamente
    """
    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conversation_id}/labels"
    headers = {
        'api_access_token': CHATWOOT_API_TOKEN,
        'Content-Type': 'application/json'
    }
    payload = {'labels': labels}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        print(f"   ✅ Etiquetas actualizadas: {labels}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Error al actualizar etiquetas: {e}")
        return False


def conversation_id_to_uuid(conversation_id: int) -> str:
    """
    Convierte un conversation_id de Chatwoot a un UUID válido.
    Esto permite usar el mismo session_id para la misma conversación.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"chatwoot-{conversation_id}"))


# ============================================
# FASTAPI APP
# ============================================
app = FastAPI(
    title="DataBot - Agente IA con Chatwoot",
    description="Webhook para integrar el Agente D con Chatwoot",
    version="1.0.0"
)


@app.post("/webhook")
async def chatwoot_webhook(request: Request):
    """
    Endpoint que recibe los webhooks de Chatwoot.
    Procesa mensajes entrantes y responde usando el Agente D.
    """
    data = await request.json()
    
    # Extraer información del webhook
    event = data.get('event')
    message_type = data.get('message_type')
    conversation = data.get('conversation', {})
    labels = conversation.get('labels', [])
    message_content = data.get('content')
    conversation_id = conversation.get('id')
    sender = data.get('sender', {})
    sender_type = sender.get('type', '')
    
    # Debug
    print(f"\n{'='*60}")
    print(f"📩 Webhook recibido: {event}")
    print(f"   Conversación: {conversation_id}")
    print(f"   Tipo: {message_type}")
    print(f"   Etiquetas: {labels}")
    
    # Solo procesar mensajes entrantes (del usuario, no del bot)
    if event != 'message_created':
        return {"status": "ignored", "reason": "Not a message_created event"}
    
    if message_type != 'incoming':
        return {"status": "ignored", "reason": "Not an incoming message"}
    
    # No responder si el usuario/conversación tiene el tag "ia-off"
    if TAG_IA_OFF in labels:
        print(f"   ⏭️  Ignorado: tiene tag '{TAG_IA_OFF}' (IA desactivada)")
        return {"status": "ignored", "reason": f"User has tag '{TAG_IA_OFF}'"}
    
    if not message_content or not conversation_id:
        return {"status": "ignored", "reason": "Missing content or conversation_id"}
    
    print(f"   📝 Mensaje: {message_content[:100]}...")
    
    # Detectar si el usuario quiere hablar con un humano
    human_keywords = ['humano', 'persona', 'asesor', 'agente', 'representante', 'hablar con alguien']
    if any(keyword in message_content.lower() for keyword in human_keywords):
        print(f"   🗣️ Transferencia a humano detectada")
        
        # Actualizar etiquetas
        new_labels = [l for l in labels if l != BOT_LABEL]
        new_labels.append('atiende-humano')
        update_chatwoot_labels(conversation_id, new_labels)
        
        # Mensaje de despedida
        handoff_message = "Entendido. Un asesor humano se pondrá en contacto contigo en breve. ¡Gracias por tu paciencia!"
        send_chatwoot_message(conversation_id, handoff_message)
        
        return {"status": "success", "action": "human_handoff"}
    
    # Procesar con el Agente D
    try:
        print(f"   🤖 Procesando con Agente D...")
        
        # Convertir conversation_id a UUID para el historial
        session_id = conversation_id_to_uuid(conversation_id)
        print(f"   📝 Session ID: {session_id[:8]}...")
        
        # Llamar al agente
        respuesta = chat_con_agente(message_content, session_id)
        
        print(f"   ✅ Respuesta generada ({len(respuesta)} chars)")
        
        # Enviar respuesta a Chatwoot
        send_chatwoot_message(conversation_id, respuesta)
        
        return {"status": "success", "action": "agent_response"}
        
    except Exception as e:
        print(f"   ❌ Error al procesar: {e}")
        
        # Enviar mensaje de error
        error_message = "Disculpa, tuve un problema al procesar tu consulta. Un asesor te atenderá pronto."
        send_chatwoot_message(conversation_id, error_message)
        
        return {"status": "error", "message": str(e)}


@app.get("/")
def read_root():
    """Endpoint raíz con información del servicio."""
    return {
        "service": "DataBot - Agente IA",
        "version": "1.0.0",
        "agent": "Agente D (RAG + Internet + Memoria)",
        "model": "GPT-4.1",
        "tools": ["buscar_datapath", "buscar_internet", "obtener_fecha_hora"],
        "chatwoot_configured": all([CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID, CHATWOOT_API_TOKEN]),
        "bot_label": BOT_LABEL,
        "status": "ready"
    }


@app.get("/health")
def health_check():
    """Endpoint de salud del servicio."""
    return {
        "status": "healthy",
        "agent": "Agente D",
        "chatwoot": "connected" if all([CHATWOOT_BASE_URL, CHATWOOT_ACCOUNT_ID, CHATWOOT_API_TOKEN]) else "not configured"
    }


@app.post("/test")
async def test_agent(request: Request):
    """
    Endpoint de prueba para testear el agente sin Chatwoot.
    
    Body: {"message": "tu pregunta", "session_id": "opcional"}
    """
    data = await request.json()
    message = data.get('message', '')
    session_id = data.get('session_id', str(uuid.uuid4()))
    
    if not message:
        return {"error": "Debes proporcionar un 'message' en el body"}
    
    print(f"\n🧪 TEST - Mensaje: {message}")
    print(f"   Session: {session_id[:8]}...")
    
    try:
        respuesta = chat_con_agente(message, session_id)
        print(f"   ✅ Respuesta: {respuesta[:100]}...")
        
        return {
            "message": message,
            "session_id": session_id,
            "response": respuesta,
            "status": "success"
        }
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return {
            "message": message,
            "error": str(e),
            "status": "error"
        }


# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    print()
    print("=" * 60)
    print("🚀 INICIANDO DATABOT CON CHATWOOT")
    print("=" * 60)
    print(f"🤖 Agente: D (RAG + Internet + Memoria)")
    print(f"🧠 Modelo: GPT-4.1")
    print(f"🔧 Tools: buscar_datapath, buscar_internet, obtener_fecha_hora")
    print(f"💾 Historial: PostgreSQL")
    print(f"🏷️  Etiqueta bot (handoff): {BOT_LABEL or 'ninguna'}")
    print(f"🚫 No responde si tiene tag: {TAG_IA_OFF}")
    print("=" * 60)
    print()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
