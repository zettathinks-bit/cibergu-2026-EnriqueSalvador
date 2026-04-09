# Resumen de Desarrollo - Proyecto ViddIA (ZettaVio)

Este documento resume el estado actual del asistente de movilidad de Guadalajara para retomar el avance fácilmente.

## 🚀 Estado Actual del Proyecto

El sistema es un asistente de voz diseñado para ayudar a personas (especialmente con problemas de visión) a consultar tiempos de llegada de autobuses urbanos en Guadalajara, España.

### ✅ Desarrollado hasta ahora:
1.  **Backend (Python - FastAPI)**: Scraper de ALSA, limpieza de nombres para voz, geolocalización Haversine y servidor unificado.
2.  **Frontend (Web - Vanilla JS/CSS)**: Interfaz voice-first, parser de números complejos, integración GPS y geocodificación inversa.
3.  **Base de Datos (MySQL)**: Tabla `paradas` con IDs oficiales y nombres normalizados.

---

## 🛠️ Plan de Trabajo (Pendientes)

Tenemos un total de **10 tareas clave** divididas por prioridad:

### 🔴 PRIORIDAD 1: Calidad de Datos (Corrección Errores GPS)
1.  **Geocodificador de Plus Codes**: Crear script para convertir los `plus_code` de la DB en coordenadas `lat/lon` numéricas.
2.  **Limpieza y Sincronización**: Asegurar que las 184 paradas tengan coordenadas para evitar que el GPS "se salte" paradas cercanas.

### 🛡️ PRIORIDAD 2: Reto 15 CiberGu (CarePing Mini)
3.  **Trigger de Voz SOS**: Reconocer palabras "Ayuda" o "Emergencia" para activar el protocolo de seguridad.
4.  **Módulo de Seguridad (HMAC)**: Proteger mensajes con firmas HMAC y tokens rotatorios (Puntos extra en OffSec).
5.  **Rate Limiting**: Implementar periodo de enfriamiento anti-abuso.
6.  **Notificación Remota (Telegram)**: Integrar Bot para enviar ubicación GPS a un cuidador externo.
7.  **Estado de Batería**: Integrar la Battery API del navegador en el reporte de emergencia.
8.  **Detección de Caídas**: Usar el acelerómetro (IMU) para detectar impactos bruscos.

### 🎨 PRIORIDAD 3: Optimización y UX
9.  **Caché de Scraping**: Reducir tiempos de respuesta guardando consultas recientes de ALSA.
10. **UI Premium & Feedback**: Añadir micro-animaciones y mejorar las confirmaciones por voz del asistente.

---
*Última actualización: 06 de Abril de 2026 - v2.1 Corregida*
