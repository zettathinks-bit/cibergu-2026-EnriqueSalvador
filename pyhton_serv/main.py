"""
ZettaVio Mobility Assistant - FastAPI Server Unified
Backend + WebApp Static Server para túneles únicos (Ngrok/Cloudflare).
"""
import os
import sys
import math
import re
from datetime import datetime, timedelta
import asyncio
from typing import Optional, List
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Query, Header, Request
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import requests # Necesario para webhooks de Telegram
import hmac
import hashlib

# Inserción de ruta para módulos core
sys.path.insert(0, os.path.dirname(__file__))

# Cargar configuración desde .env
load_dotenv()

app = FastAPI(
    title="Zetta Vío (CarePing) API",
    description="Asistente de movilidad y seguridad urbana Guadalajara",
    version="2.1.0"
)

# --- CONFIGURACIÓN CRÍTICA (RETO CIBERGU) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
SHARED_SECRET = os.getenv("SHARED_SECRET")
# --------------------------------------------

# --- SISTEMA DE CACHÉ Y CONCURRENCIA ---
bus_cache = {}
locks = {}
CACHE_SECONDS = 45 

# --- ESCUDO ANTI-ATAQUES (RATE LIMITING) ---
user_requests = {}
LIMIT_BUS = 3.0 # Segundos entre peticiones
LIMIT_SOS = 30.0 # Segundos entre alarmas

def verify_rate_limit(ip: str, endpoint: str, limit: float) -> bool:
    """Evita el abuso del servidor (DoS)"""
    global user_requests
    now = datetime.now().timestamp()
    
    key = f"{ip}:{endpoint}"
    last_time = user_requests.get(key)
    
    if last_time and (now - last_time) < limit:
        print(f"🛑 BLOQUEADO: {key} (Faltan {round(limit - (now - last_time), 1)}s)")
        return False
        
    user_requests[key] = now
    return True

def get_address_google(lat, lon):
    """Obtiene la dirección exacta usando la API Premium de Google Maps"""
    if not GOOGLE_MAPS_API_KEY:
        return "Ubicación mediante coordenadas"
    
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key={GOOGLE_MAPS_API_KEY}&language=es"
    try:
        r = requests.get(url, timeout=5)
        data = r.json()
        if data["status"] == "OK":
            # La primera dirección suele ser la más precisa (Calle + Número)
            raw_address = data["results"][0]["formatted_address"]
            # Limpiar para voz humana
            return clean_for_voice(raw_address)
        return "Ubicación desconocida"
    except Exception as e:
        print(f"❌ Error en Google Maps: {e}")
        return "Error al consultar Google Maps"

def get_walking_instructions(origin_lat, origin_lon, dest_lat, dest_lon):
    """Obtiene ruta a pie usando la nueva Routes API (V2) de Google"""
    if not GOOGLE_MAPS_API_KEY:
        return ["La navegación no está configurada."]
    
    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": "routes.legs.steps.navigationInstruction"
    }
    
    body = {
        "origin": {
            "location": { "latLng": { "latitude": origin_lat, "longitude": origin_lon } }
        },
        "destination": {
            "location": { "latLng": { "latitude": dest_lat, "longitude": dest_lon } }
        },
        "travelMode": "WALK",
        "languageCode": "es-ES",
        "units": "METRIC"
    }
    
    try:
        r = requests.post(url, json=body, headers=headers, timeout=5)
        data = r.json()
        
        # Super Debug: Ver qué responde el nuevo motor
        # print(f"📡 Nueva Routes API responde: {data}")

        if "routes" in data and len(data["routes"]) > 0:
            steps = data["routes"][0]["legs"][0]["steps"]
            instrucciones = []
            for s in steps:
                text = s.get("navigationInstruction", {}).get("instructions", "")
                if text:
                    # Limpieza para voz humana
                    # Buscamos todas las variantes de "C." al inicio o después de un espacio
                    reemplazos = {
                        "C. ": "Calle ", "C/ ": "Calle ", "C./ ": "Calle ",
                        "c. ": "Calle ", "c/ ": "Calle ",
                        "Av. ": "Avenida ", "av. ": "Avenida ",
                        "Pza. ": "Plaza ", "Pz. ": "Plaza ",
                        "Ctra. ": "Carretera ", "ctra. ": "Carretera "
                    }
                    for ori, rep in reemplazos.items():
                        text = text.replace(ori, rep)
                    
                    # Eliminar HTML sutil que Maps a veces mete (si existiera)
                    text = re.sub(r'<[^>]+>', '', text)
                    text = text.replace("  ", " ").strip()
                    instrucciones.append(text)
            return instrucciones
        
        print(f"❌ Error en Routes V2: {data}")
        return ["No he podido calcular el camino con el nuevo mapa."]
    except Exception as e:
        print(f"❌ Error de conexión Routes V2: {e}")
        return ["Fallo al conectar con el motor de rutas."]


class SOSAlert(BaseModel):
    lat: float
    lon: float
    address: Optional[str] = "Ubicación desconocida"
    battery: Optional[float] = 0
    accuracy: Optional[float] = 0

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_scraper():
    """Instancia un nuevo scraper para cada petición, evitando conflictos de ViewState."""
    from core.bus_extractor import ZettaVioBusScraper
    return ZettaVioBusScraper()

def calcular_distancia_metros(lat1, lon1, lat2, lon2):
    """Haversine formula - distancia real en metros entre dos coordenadas GPS"""
    R = 6371000  # Radio de la Tierra en metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ------------------------------------------------------------------ #
#   Gestión de Paradas (MySQL Oficial)                              #
# ------------------------------------------------------------------ #
import mysql.connector

# Diccionario de Limpieza Humana: De ALSA a Voz Natural
DIMINUTIVOS = {
    r"FcoAritio": "Francisco Aritio",
    r"Fco Aritio": "Francisco Aritio",
    r"Pº": "Paseo ", "Pz": "Plaza ", "Gta": "Glorieta ",
    r"Pza": "Plaza ", "Av\.": "Avenida ", "C\.": "Calle ", "C/": "Calle ",
    r"ConArenal": "Concepción Arenal", "AguasVivas": "Aguas Vivas",
    r"RENFE": "Estación Renfe", "CriColon": "Cristóbal Colón",
    r"FcoPizarro": "Francisco Pizarro", "S\.Isidro": "San Isidro",
    r"S\.Gines": "San Ginés", "MPinilla": "Mariano Pinilla",
    r"EduGuitian": "Eduardo Guitián", "Pq": "Parque ",
    r"Ctra": "Carretera ", "Fdez\.Iparraguirre": "Fernández Iparraguirre",
    r"Cifuentes": "Calle Cifuentes", "Besteiro": "Calle Capitán Boixareu Rivera",
    r"Casas Rio": "Casas del Río", "PzCaidos": "Plaza de los Caídos",
    r"ant": "antiguo", "DES": "después", "ANT": "antes", "frte": "frente"
}

def clean_for_voice(text: str) -> str:
    """Convierte abreviaturas feas de ALSA en nombres bonitos para la voz"""
    res = text
    for abrev, natural in DIMINUTIVOS.items():
        # Usamos \b para que solo reemplace si la abreviatura es una palabra completa
        # Evitamos casos como "Manantiales" -> "Manantiguoiales"
        res = re.sub(rf"\b{abrev}\b", natural, res, flags=re.IGNORECASE)
    
    # Limpieza final de barras y paréntesis
    res = res.replace('/', ' con ').replace('(', '').replace(')', '').strip()
    return res

def get_mysql_db():
    return mysql.connector.connect(
        host="127.0.0.1",
        user="root",
        password="",
        database="zettavio"
    )

def find_closest_stop(lat: float, lon: float):
    """Búsqueda en MySQL por distancia Haversine (metros reales).
    Prioriza paradas con lat/lon. Si no hay ninguna, devuelve la más cercana con plus_code.
    """
    try:
        db = get_mysql_db()
        cursor = db.cursor(dictionary=True)
        # Intentar con plus_code column - si no existe, fallback sin él
        try:
            cursor.execute(
                "SELECT id, nombre, lat, lon, plus_code FROM paradas WHERE lat IS NOT NULL AND activa = 1"
            )
        except Exception:
            cursor.execute(
                "SELECT id, nombre, lat, lon, NULL as plus_code FROM paradas WHERE lat IS NOT NULL AND activa = 1"
            )
        paradas_con_coords = cursor.fetchall()
        cursor.close()
        db.close()

        mejor = None
        dist_min = float('inf')

        for p in paradas_con_coords:
            d = calcular_distancia_metros(lat, lon, float(p['lat']), float(p['lon']))
            if d < dist_min:
                dist_min = d
                mejor = p

        return mejor, dist_min
    except Exception as e:
        print(f"Error consultando MySQL: {e}")
        return None, float('inf')

def get_stop_data(stop_id: str):
    """Obtiene el nombre Amigable y las COORDENADAS de una parada"""
    try:
        db = get_mysql_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT nombre, lat, lon FROM paradas WHERE id = %s", (stop_id,))
        row = cursor.fetchone()
        cursor.close()
        db.close()
        
        if row:
            return {
                "nombre": clean_for_voice(row['nombre']),
                "lat": float(row['lat']) if row['lat'] is not None else None,
                "lon": float(row['lon']) if row['lon'] is not None else None
            }
        return {"nombre": f"{stop_id}", "lat": None, "lon": None}
    except Exception as e:
        print(f"Error en get_stop_data: {e}")
        return {"nombre": f"{stop_id}", "lat": None, "lon": None}

# ------------------------------------------------------------------ #
#   Lógica de Narración de Voz                                       #
# ------------------------------------------------------------------ #
def voice_text_from_data(data: dict, user_coords: Optional[dict] = None) -> str:
    if data.get("error"):
        return "Lo siento, el servidor de autobuses de Guadalajara parece estar ocupado. Inténtalo en un momento."
    
    buses = data.get("buses", [])
    stop_id = data.get("parada", "")
    info_parada = get_stop_data(stop_id)
    stop_name = info_parada["nombre"]
    
    # 1. Calcular distancia si tenemos coordenadas del usuario y de la parada
    dist_msg = ""
    if user_coords and info_parada["lat"] and info_parada["lon"]:
        d = calcular_distancia_metros(
            user_coords["lat"], user_coords["lon"],
            info_parada["lat"], info_parada["lon"]
        )
        dist_msg = f" que está a unos {round(d)} metros de tu posición,"
    
    # Formato pedido: "En la parada 170, Ejercito 15..."
    full_stop_label = f"{stop_id}, {stop_name}"
    
    if not buses:
        return f"En la parada {full_stop_label},{dist_msg} no hay autobuses próximos ahora mismo."
    
    text = f"En la parada {full_stop_label},{dist_msg} "
    for b in buses:
        # Limpieza inteligente: evita el error "minutosutos" (double replacement)
        m_raw = b['minutos'].lower().strip()
        if "proxim" in m_raw or "llegando" in m_raw:
            mins_voz = "está llegando ahora mismo"
        else:
            # Quitamos el punto si existe para facilitar regex
            m_text = m_raw.replace(".", "")
            # Reemplazar 'm' o 'min' solo si son palabras sueltas
            mins_voz = re.sub(r'\b(m|min)\b', 'minutos', m_text)
            # Limpieza final de espacios
            mins_voz = mins_voz.replace("  ", " ").strip()
                
        text += f"el autobús de la línea {b['linea']} hacia {b['itinerario']} {mins_voz}. "
    return text

# ------------------------------------------------------------------ #
#   Endpoints de la API                                               #
# ------------------------------------------------------------------ #
# ------------------------------------------------------------------ #
#   CIBERGU - Reto 15 (CarePing Mini)                                #
# ------------------------------------------------------------------ #
def send_telegram_alert(alert: SOSAlert):
    """Envía un mensaje de SOS a Telegram con formato de alta prioridad"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Alerta omitida: Telegram no configurado.")
        return False

    maps_url = f"https://www.google.com/maps?q={alert.lat},{alert.lon}"
    
    mensaje = (
        f"🚨 <b>ZETTA VIO: ALERTA DE EMERGENCIA</b> 🚨\n\n"
        f"🆘 <b>TIPO:</b> SOS ACTIVADO (VOZ/CAÍDA)\n"
        f"📍 <b>UBICACIÓN:</b> {alert.address}\n"
        f"🔋 <b>BATERÍA:</b> {int(alert.battery)}%\n"
        f"🗺️ <b>MAPA:</b> <a href='{maps_url}'>Ver posición en tiempo real</a>\n\n"
        f"⚠️ <i>Por favor, contacte con el usuario de inmediato.</i>"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"❌ Error enviando Telegram: {e}")
        return False

@app.post("/emergency/alert", tags=["CiberGu"])
def receive_sos(alert: SOSAlert, request: Request, x_signature: str = Header(None)):
    """Recibe alertas SOS validadas con HMAC y Rate Limiting (Reto 15)"""
    user_ip = request.client.host
    
    # 🛡️ ESCUDO: Rate Limiting
    if not verify_rate_limit(user_ip, "sos", LIMIT_SOS):
        raise HTTPException(status_code=429, detail="SOS Bloqueado por saturación (Rate Limit).")

    # 1. ACTUALIZAR DIRECCIÓN CON GOOGLE PREMIUM
    address_premium = get_address_google(alert.lat, alert.lon)
    alert.address = address_premium

    # 2. VALIDACIÓN DE FIRMA (HMAC-SHA256)
    if not x_signature:
        raise HTTPException(status_code=401, detail="Firma de seguridad ausente")

    # Re-generar firma localmente para comparar (usando redondeo para evitar fallos de precisión)
    msg_str = f"{round(alert.lat, 6)}{round(alert.lon, 6)}{int(alert.battery)}"
    message = msg_str.encode()
    expected_sig = hmac.new(SHARED_SECRET.encode(), message, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(x_signature, expected_sig):
        print(f"🛑 ATAQUE DETECTADO: Firma inválida de {alert.lat}, {alert.lon}")
        raise HTTPException(status_code=403, detail="Firma de seguridad inválida")

    print(f"🆘 SOS AUTÉNTICO RECIBIDO: {alert.address} ({alert.lat}, {alert.lon})")
    
    enviado = send_telegram_alert(alert)
    
    return {
        "status": "success",
        "message": "Alerta de emergencia procesada",
        "telegram_notified": enviado
    }

@app.get("/bus/tiempos", tags=["Movilidad"])
def get_bus_tiempos(stop_id: str, request: Request, lat: Optional[float] = None, lon: Optional[float] = None):
    """Obtiene tiempos de bus con Rate Limiting (Síncrono para Playwright)"""
    user_ip = request.client.host
    
    # 🛡️ ESCUDO: Rate Limiting
    if not verify_rate_limit(user_ip, "bus", LIMIT_BUS):
        raise HTTPException(status_code=429, detail="Cálmate, vaquero. Demasiadas peticiones de bus.")

    scraper = get_scraper()
    res = scraper.get_times(stop_id)
    
    user_coords = {"lat": lat, "lon": lon} if lat and lon else None
    res["voz"] = voice_text_from_data(res, user_coords)
    return res

@app.get("/bus/cercana", tags=["Transporte"])
def get_parada_cercana(lat: float, lon: float):
    p, d = find_closest_stop(lat, lon)
    if not p:
        raise HTTPException(status_code=404, detail="No hay paradas cerca")
    nombre_limpio = clean_for_voice(p['nombre'])
    return {
        "parada_id": p["id"],
        "nombre": nombre_limpio,
        "distancia": round(d, 1),
        "plus_code": p.get("plus_code")
    }

@app.get("/navigation/guide", tags=["Utilidades"])
def get_guide_to_stop(stop_id: str, lat: float, lon: float):
    """Busca una parada y devuelve los pasos para llegar a ella"""
    # 1. Buscar coordenadas de la parada en la DB
    try:
        db = get_mysql_db()
        cursor = db.cursor(dictionary=True)
        # Algunos IDs pueden venir como texto "101" o con espacios
        cursor.execute("SELECT nombre, lat, lon FROM paradas WHERE id = %s", (str(stop_id).strip(),))
        stop = cursor.fetchone()
        cursor.close()
        db.close()
    except Exception as e:
        print(f"❌ Error DB en Navegación: {e}")
        return {"error": "Error al conectar con la base de datos de paradas."}
    
    if not stop or not stop['lat'] or not stop['lon']:
        print(f"⚠️ Parada {stop_id} no encontrada o sin coordenadas.")
        return {"error": "No tengo las coordenadas de esa parada."}
    
    # 2. Obtener pasos de Google
    print(f"🔍 Pidiendo ruta: Desde ({lat},{lon}) hasta Parada {stop_id} ({stop['lat']},{stop['lon']})")
    pasos = get_walking_instructions(lat, lon, stop['lat'], stop['lon'])
    
    return {
        "parada": stop['nombre'],
        "pasos": pasos,
        "total_pasos": len(pasos),
        "destLat": float(stop['lat']),
        "destLon": float(stop['lon'])
    }

@app.get("/utility/address", tags=["Utilidades"])
def get_current_address(lat: float, lon: float):
    """Endpoint para que el móvil pida la dirección a Google de forma SEGURA"""
    addr = get_address_google(lat, lon)
    return {"address": addr}

# ------------------------------------------------------------------ #
#   Servicio de Archivos Estáticos (Frontend)                         #
# ------------------------------------------------------------------ #
# Nota: La webapp está en la carpeta superior raíz /webapp
WEBAPP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "webapp"))

@app.get("/", tags=["Frontend"])
def main_page():
    index_file = os.path.join(WEBAPP_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"error": f"WebApp no encontrada en {WEBAPP_DIR}"}

if os.path.exists(WEBAPP_DIR):
    app.mount("/static", StaticFiles(directory=WEBAPP_DIR), name="static")
    # Redirección de archivos root comunes
    @app.get("/app.js")
    async def get_js(): return FileResponse(os.path.join(WEBAPP_DIR, "app.js"))
    @app.get("/style.css")
    async def get_css(): return FileResponse(os.path.join(WEBAPP_DIR, "style.css"))
    @app.get("/manifest.json")
    async def get_manifest(): return FileResponse(os.path.join(WEBAPP_DIR, "manifest.json"))

# ------------------------------------------------------------------ #
#   Archivos Estáticos - DEBE IR AL FINAL para no bloquear la API     #
# ------------------------------------------------------------------ #
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "webapp"))
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
