/* 
  ZettaVio Mobility Assistant - Frontend V2.0
  - Sin botón GPS separado. Solo el microfono.
  - GPS sin caché (maximumAge: 0)
  - Plus Code como fallback para paradas sin lat/lon
*/

const transcriptionText = document.getElementById('transcription-text');
const micBtn = document.getElementById('mic-btn');
const arrivalsList = document.getElementById('arrivals-list');

// --- ÚLTIMO ESTADO PARA "REPITE" Y GPS ---
let lastVoiceResponse = "Todavía no he realizado ninguna consulta.";
let userLat = null;
let userLon = null;
let lastAddress = "Ubicación desconocida";
let lastAccuracy = 0;
let isEmergencyActive = false;
let destCoords = null; // Guardar destino para consulta de distancia
const SHARED_SECRET = "zettavio-secret-2026";

function speak(text) {
    if (!('speechSynthesis' in window)) return;
    lastVoiceResponse = text;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'es-ES';
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    transcriptionText.classList.add('pulse-voice');
    setTimeout(() => transcriptionText.classList.remove('pulse-voice'), 2000);
    window.speechSynthesis.speak(utterance);
}

// --- DICCIONARIO DE VOZ ---
const numberMap = {
    "uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5",
    "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10",
    "once": "11", "doce": "12", "trece": "13", "catorce": "14", "quince": "15",
    "dieciséis": "16", "diecisiete": "17", "dieciocho": "18", "diecinueve": "19", "veinte": "20",
    "veintiuno": "21", "veintidós": "22", "veintitrés": "23", "veinticuatro": "24",
    "veinticinco": "25", "veintiséis": "26", "veintisiete": "27", "veintiocho": "28",
    "veintinueve": "29", "treinta": "30", "cuarenta": "40", "cincuenta": "50",
    "sesenta": "60", "setenta": "70", "ochenta": "80", "noventa": "90",
    "cien": "100", "ciento": "100", "ciento": "100",
    "ciento diez": "110", "ciento veinte": "120", "ciento treinta": "130",
    "ciento cuarenta": "140", "ciento cincuenta": "150", "ciento sesenta": "160",
    "ciento setenta": "170", "ciento ochenta": "180",
    "doscientos": "200", "trescientos": "300"
};

function parseNumberFromVoice(text) {
    const cleanText = text.toLowerCase().trim();

    if (cleanText.includes("repite") || cleanText.includes("otra vez") || cleanText.includes("repita") || cleanText.includes("qué has dicho")) {
        console.log("Intent: REPEAT ->", lastVoiceResponse);
        speak(lastVoiceResponse);
        return "INTENT_REPEAT";
    }

    if (cleanText.includes("gps") || cleanText.includes("cerca") ||
        cleanText.includes("dónde") || cleanText.includes("donde") ||
        cleanText.includes("estoy") || cleanText.includes("posición") ||
        cleanText.includes("parada más cercana")) {
        triggerGPS();
        return "INTENT_GPS";
    }

    if (cleanText.includes("cuánto queda") || cleanText.includes("cuanto queda") || 
        cleanText.includes("cuánto me falta") || cleanText.includes("cuanto me falta") ||
        cleanText.includes("distancia")) {
        
        if (destCoords) {
            speakDistanceLeft();
            return "INTENT_DIST";
        } else {
            speak("Primero dime a qué parada quieres ir. Por ejemplo: guíame a la parada 170.");
            return "INTENT_DIST_ERR";
        }
    }

    if (cleanText.includes("guíame") || cleanText.includes("guia me") || 
        cleanText.includes("cómo llego") || cleanText.includes("como llego") ||
        cleanText.includes("instrucciones para ir") || cleanText.includes("ruta a")) {
        
        const stopIdMatch = cleanText.match(/\d+/);
        if (stopIdMatch) {
            startNavigation(stopIdMatch[0]);
            return "INTENT_NAV";
        }
        speak("Dime a qué parada quieres que te guíe.");
        return "INTENT_NAV_ERR";
    }

    if (cleanText.includes("ayuda") || cleanText.includes("socorro") || cleanText.includes("sos") || 
        cleanText.includes("emergencia") || cleanText.includes("qué haces") || cleanText.includes("quién")) {
        
        // PRIORIDAD CIBERGU: Disparo inmediato de SOS si detecta palabras clave críticas
        if (cleanText.includes("ayuda") || cleanText.includes("emergencia") || cleanText.includes("socorro") || cleanText.includes("sos")) {
            triggerEmergency();
            return "INTENT_EMERGENCY";
        }
        
        speak("Hola, soy Zetta Vío, tu asistente personal de Guadalajara. Puedo decirte cuándo viene el bus si me dices el número de parada. También puedo guiarte paso a paso si me dices 'Guíame a la parada tal'. Y si te encuentras en peligro, solo grita 'Socorro' o 'Auxilio' para avisar a tus familiares con tu ubicación exacta. ¿En qué puedo ayudarte?");
        return "INTENT_HELP";
    }

    // 1. Lógica aditiva robusta (ej: "ciento" + "cincuenta" + "y" + "ocho" = 158)
    let total = 0;
    let foundNumber = false;
    
    // Limpiamos el texto de conectores como "y" para que no molesten
    const words = cleanText.replace(/\b y \b/g, ' ').split(/\s+/);
    
    words.forEach(word => {
        if (numberMap[word]) {
            total += parseInt(numberMap[word]);
            foundNumber = true;
        }
    });

    if (foundNumber && total > 0) {
        console.log("Parsed Voice Number:", total);
        return total.toString();
    }

    // 3. Dígitos directos
    const match = cleanText.match(/\d+/);
    return match ? match[0] : null;
}

// --- GPS SIN CACHÉ ---
function triggerGPS() {
    if (!navigator.geolocation) {
        speak("Tu dispositivo no tiene GPS activo.");
        return;
    }

    speak("Analizando tu posición, espera.");
    transcriptionText.textContent = "Obteniendo GPS...";

    navigator.geolocation.getCurrentPosition(
        async (pos) => {
            userLat = pos.coords.latitude;
            userLon = pos.coords.longitude;
            lastAccuracy = Math.round(pos.coords.accuracy);

            try {
                const responseStop = await fetch(`/bus/cercana?lat=${userLat}&lon=${userLon}`);
                const stopData = await responseStop.json();

                let addressText = "tu posición actual";
            try {
                // Reverse geocoding PREMIUM via ZettaVio Backend (Google)
                const addrRes = await fetch(`/utility/address?lat=${userLat}&lon=${userLon}`);
                const addrData = await addrRes.json();
                addressText = addrData.address || "tu posición actual";
            } catch (_) {
                console.error("Error Google Maps Utility:", _);
            }

                if (stopData.parada_id) {
                    const dist = Math.round(stopData.distancia);
                    const precisionMsg = lastAccuracy > 50 ? ` La precisión del GPS es de ${lastAccuracy} metros.` : '';
                    lastAddress = addressText;
                    speak(`Te encuentras en ${addressText}. La parada más cercana es la ${stopData.parada_id}, ${stopData.nombre}, a unos ${dist} metros.${precisionMsg}`);
                    transcriptionText.textContent = `📍 ${addressText}`;
                    fetchBusData(stopData.parada_id, false);
                } else {
                    speak(`Estás en ${addressText}, pero no encontré paradas de urbanos cercanas.`);
                }

            } catch (error) {
                speak("He obtenido tu posición, pero el servidor de paradas no responde.");
            }
        },
        (err) => {
            speak("No he podido acceder a tu GPS. Revisa los permisos.");
        },
        {
            enableHighAccuracy: true,
            timeout: 20000,
            maximumAge: 0      // ← CLAVE: nunca usar caché de posición
        }
    );
}

// --- LÓGICA DE EMERGENCIA (CIBERGU - RETO 15) ---
async function triggerEmergency() {
    if (isEmergencyActive) return;
    isEmergencyActive = true;

    // --- CAMBIO VISUAL SOS IMPACTANTE ---
    speak("Protocolo de emergencia de Zetta Vío activado. Avisando a tus familiares y obteniendo tu ubicación exacta. Mantén la calma.");
    transcriptionText.textContent = "🆘 MODO EMERGENCIA ACTIVADO 🆘";
    document.body.classList.add('emergency-mode');
    
    // Cambiar icono del mic a campana y color a rojo SOS
    micBtn.classList.add('sos-active');
    micBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
        </svg>
    `;

    // Obtener batería y enviar SOS
    let batteryLevel = 0;
    try {
        const battery = await navigator.getBattery();
        batteryLevel = Math.round(battery.level * 100);
    } catch (_) {}

    // 2. Obtener Ubicación y Dirección REAL antes de enviar
    navigator.geolocation.getCurrentPosition(async (pos) => {
        userLat = pos.coords.latitude;
        userLon = pos.coords.longitude;
        lastAccuracy = pos.coords.accuracy;

        try {
            // Reverse geocoding PREMIUM via ZettaVio Backend (Google)
            const addrRes = await fetch(`/utility/address?lat=${userLat}&lon=${userLon}`);
            const addrData = await addrRes.json();
            lastAddress = addrData.address || "Ubicación detectada por coordenadas";
        } catch (e) {
            console.warn("No se pudo sacar la calle, se usaron coordenadas.");
        }

        sendEmergencyPayload(batteryLevel);
    }, (err) => {
        console.error("Error GPS en SOS:", err);
        sendEmergencyPayload(batteryLevel); // Enviar aunque sea con datos viejos
    }, { enableHighAccuracy: true, timeout: 5000 });

    // Reset tras 30 segundos (Cooling Period)
    setTimeout(() => {
        isEmergencyActive = false;
        document.body.classList.remove('emergency-mode');
    }, 30000);
}

async function generateSignature(message) {
    const encoder = new TextEncoder();
    const keyData = encoder.encode(SHARED_SECRET);
    const msgData = encoder.encode(message);

    const cryptoKey = await crypto.subtle.importKey(
        'raw', keyData, { name: 'HMAC', hash: 'SHA-256' },
        false, ['sign']
    );

    const signatureArrayBuffer = await crypto.subtle.sign('HMAC', cryptoKey, msgData);
    return Array.from(new Uint8Array(signatureArrayBuffer))
        .map(b => b.toString(16).padStart(2, '0'))
        .join('');
}

async function sendEmergencyPayload(battery) {
    try {
        // Redondear para firma (consistente con el servidor)
        const latRef = Number(userLat).toFixed(6);
        const lonRef = Number(userLon).toFixed(6);
        
        // Generar firma HMAC
        const message = `${latRef}${lonRef}${battery}`;
        const signature = await generateSignature(message);

        await fetch('/emergency/alert', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'X-Signature': signature
            },
            body: JSON.stringify({
                lat: userLat,
                lon: userLon,
                address: lastAddress,
                battery: battery,
                accuracy: lastAccuracy
            })
        });
    } catch (e) {
        console.error("Error enviando SOS:", e);
    }
}

let navigationWatchId = null;

// --- LÓGICA DE NAVEGACIÓN (GOOGLE DIRECTIONS) ---
async function startNavigation(stopId) {
    // Limpiar rastreadores antiguos
    if (navigationWatchId) navigator.geolocation.clearWatch(navigationWatchId);

    if (!userLat || !userLon) {
        speak("Necesito tu ubicación GPS para guiarte. Espera un momento.");
        // Obtener una primera posición rápida
        navigator.geolocation.getCurrentPosition((pos) => {
            userLat = pos.coords.latitude;
            userLon = pos.coords.longitude;
            startNavigation(stopId);
        }, () => {}, { enableHighAccuracy: true });
        return;
    }

    speak(`Buscando ruta a pie a la parada ${stopId}, un momento.`);
    try {
        const res = await fetch(`/navigation/guide?stop_id=${stopId}&lat=${userLat}&lon=${userLon}`);
        const data = await res.json();

        if (data.error) {
            speak(data.error);
            return;
        }

        // Guardar destino inmediatamente
        destCoords = { 
            lat: Number(data.destLat), 
            lon: Number(data.destLon) 
        };
        console.log("📍 Destino fijado:", destCoords);

        // --- CAMBIO DE ICONO A BRÚJULA ---
        micBtn.classList.add('nav-active');
        micBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"></polygon>
            </svg>
        `;

        // 1. Narrar instrucciones iniciales
        speak(`Ruta encontrada hacia ${data.parada}. Aquí tienes las instrucciones.`);
        let delay = 3500;
        data.pasos.forEach((paso, index) => {
            setTimeout(() => {
                speak(`${index + 1}. ${paso}`);
                transcriptionText.textContent = `🧭 Paso ${index + 1}: ${paso}`;
            }, delay);
            delay += (paso.length * 65) + 2000; 
        });

        // 2. ACTIVAR RASTREADOR DE LLEGADA (Watch)
        navigationWatchId = navigator.geolocation.watchPosition((pos) => {
            // ACTUALIZAR POSICIÓN GLOBAL
            userLat = pos.coords.latitude;
            userLon = pos.coords.longitude;
            
            // Calculamos distancia
            const dist = calculateSimpleDist(userLat, userLon, destCoords.lat, destCoords.lon);
            
            if (dist < 15) { // Si estamos a menos de 15 metros
                speak("¡Atención! Has llegado a tu destino. La parada está justo aquí.");
                if (navigator.vibrate) navigator.vibrate([500, 200, 500]);
                navigator.geolocation.clearWatch(navigationWatchId);
                navigationWatchId = null;
                destCoords = null;
                transcriptionText.textContent = "📍 ¡HAS LLEGADO!";
                document.body.classList.remove('navigating');
                resetMicIcon();
            }
        }, null, { enableHighAccuracy: true, maximumAge: 0 });

    } catch (e) {
        speak("Error de conexión al obtener la ruta.");
    }
}

function speakDistanceLeft() {
    speak("Calculando distancia, un momento.");

    navigator.geolocation.getCurrentPosition((pos) => {
        const uLat = pos.coords.latitude;
        const uLon = pos.coords.longitude;
        const dLat = parseFloat(destCoords.lat);
        const dLon = parseFloat(destCoords.lon);

        console.log("📍 GPS:", uLat, uLon, "→ Destino:", dLat, dLon);

        if (isNaN(dLat) || isNaN(dLon)) {
            speak("Hay un problema con las coordenadas de la parada.");
            return;
        }

        const dist = calculateSimpleDist(uLat, uLon, dLat, dLon);
        speak(`Te faltan aproximadamente ${Math.round(dist)} metros para llegar a la parada.`);

    }, () => {
        speak("No puedo acceder al GPS. Asegúrate de tener la ubicación activada.");
    }, { enableHighAccuracy: true, timeout: 8000, maximumAge: 5000 });
}

function resetMicIcon() {
    micBtn.classList.remove('nav-active', 'sos-active');
    micBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
            <line x1="12" y1="19" x2="12" y2="23"></line>
            <line x1="8" y1="23" x2="16" y2="23"></line>
        </svg>
    `;
}

// Función auxiliar para distancia simple
function calculateSimpleDist(lat1, lon1, lat2, lon2) {
    const R = 6371e3; 
    const p1 = lat1 * Math.PI/180;
    const p2 = lat2 * Math.PI/180;
    const dp = (lat2-lat1) * Math.PI/180;
    const dl = (lon2-lon1) * Math.PI/180;
    const a = Math.sin(dp/2) * Math.sin(dp/2) +
              Math.cos(p1) * Math.cos(p2) *
              Math.sin(dl/2) * Math.sin(dl/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c; 
}

// --- LÓGICA DE BUS ---
async function fetchBusData(stopId, shouldSpeakResult = true) {
    arrivalsList.innerHTML = `<div class="loading-spinner"></div><p style="text-align:center;color:#6b7db3;margin-top:0.5rem">Consultando...</p>`;
    if (shouldSpeakResult) speak("Conectando con el servidor de Guadalajara, un momento...");

    try {
        let url = `/bus/tiempos?stop_id=${stopId}`;
        if (userLat && userLon) {
            url += `&lat=${userLat}&lon=${userLon}`;
        }
        const response = await fetch(url);
        const data = await response.json();
        if (shouldSpeakResult) {
            speak(data.voz || "No hay estimaciones en este momento.");
        }
        displayBusData(data);
    } catch (error) {
        arrivalsList.innerHTML = `<p class="error-text" style="text-align:center;color:#f43f5e;padding:1rem">Fallo de red al conectar con ALSA.</p>`;
        speak("He tenido un problema de red al conectar con el servidor oficial.");
    }
}

function displayBusData(data) {
    arrivalsList.innerHTML = '';
    const buses = data.buses || [];

    if (buses.length === 0) {
        arrivalsList.innerHTML = `<div class="no-data">Sin autobuses próximos en la parada ${data.parada || ''}.</div>`;
        return;
    }

    buses.forEach(bus => {
        const card = document.createElement('div');
        card.className = 'bus-card';
        card.innerHTML = `
            <div class="line-badge">${bus.linea}</div>
            <div class="itinerary">${bus.itinerario}</div>
            <div class="arrival-time">${bus.minutos}</div>
        `;
        arrivalsList.appendChild(card);
    });
}

// --- RECONOCIMIENTO DE VOZ ---
let recognition;
let isListening = false;

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'es-ES';

    recognition.onstart = () => {
        isListening = true;
        micBtn.classList.add('mic-active');
        transcriptionText.textContent = "Escuchando...";
        transcriptionText.classList.remove('placeholder');
    };

    recognition.onresult = (event) => {
        const text = event.results[0][0].transcript;
        transcriptionText.textContent = `"${text}"`;
        recognition.stop();
        stopListeningUI();

        const result = parseNumberFromVoice(text);
        
        if (!result) return;
        if (result.toString().startsWith("INTENT_")) return;

        // Evitar que peticiones simultaneas hagan que la voz se repita
        if (window.isFetching) return;
        window.isFetching = true;
        
        setTimeout(() => {
            fetchBusData(result).finally(() => { window.isFetching = false; });
        }, 150);
    };

    recognition.onerror = (event) => {
        console.error("Error de voz:", event.error);
        stopListeningUI();
        if (event.error === 'not-allowed') {
            speak("Necesito permiso para usar el micrófono.");
        }
    };

    recognition.onend = () => stopListeningUI();
}

function stopListeningUI() {
    isListening = false;
    micBtn.classList.remove('mic-active');
}

// --- DETECCIÓN DE CAÍDAS (IMU) ---
const FALL_THRESHOLD = 25; // Sensibilidad del impacto m/s^2 (Aprox 2.5G)
let lastFallCheck = 0;

if (window.DeviceMotionEvent) {
    window.addEventListener('devicemotion', (event) => {
        if (isEmergencyActive) return;

        const acc = event.accelerationIncludingGravity;
        if (!acc) return;

        // Calcular la magnitud total de la aceleración
        const totalAcc = Math.sqrt(acc.x ** 2 + acc.y ** 2 + acc.z ** 2);

        // Si hay un impacto fuerte
        if (totalAcc > FALL_THRESHOLD) {
            const now = Date.now();
            if (now - lastFallCheck > 5000) { // Evitar disparos múltiples en el mismo segundo
                lastFallCheck = now;
                console.log("¡Impacto detectado!", totalAcc);
                
                // Pequeña vibración si el móvil lo permite
                if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
                
                // Disparar SOS
                triggerEmergency();
            }
        }
    });
}

// --- ACTIVACIÓN POR TODA LA PANTALLA ---
document.body.addEventListener('click', (e) => {
    // Si se hace click en un botón real, dejamos que su propio listener actúe
    if (e.target.closest('button')) return;
    toggleMic();
});

function toggleMic() {
    if (!recognition) {
        speak("Tu navegador no soporta reconocimiento de voz.");
        return;
    }
    if (isListening) {
        recognition.stop();
    } else {
        recognition.start();
    }
}

micBtn.addEventListener('click', (e) => {
    e.stopPropagation(); // Evitar doble disparo con el click del body
    toggleMic();
});
