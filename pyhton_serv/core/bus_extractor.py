"""
ZettaVio Bus Scraper - Playwright 3.1
Estrategia robusta: esperar networkidle tras cada acción.
"""
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = 'http://urbanos.guadalajara.es/tiempos/tiemposParada.xhtml'

class ZettaVioBusScraper:
    def get_times(self, stop_id: str) -> dict:
        with sync_playwright() as p:
            # Usar chromium headless de forma genérica
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                locale='es-ES',
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                extra_http_headers={'Accept-Language': 'es-ES,es;q=0.9'}
            )
            page = context.new_page()

            try:
                # PASO 1 MAGISTRAL: Cargar la portada para instanciar la sesión JSF correctamente
                print(f"[PW] Cargando portada oficial para parada {stop_id}...")
                page.goto('http://urbanos.guadalajara.es/', wait_until='networkidle', timeout=25000)

                # Hacer clic en la pestaña 'Tiempos' inicializa la lista en el backend
                btn_tiempos = page.locator('span', has_text='Tiempos').first
                btn_tiempos.wait_for(state='visible', timeout=10000)
                btn_tiempos.click()
                
                # Esperar a que la tabla de paradas se llene (evita el "No hay paradas registradas")
                print("[PW] Esperando carga de paradas desde backend...")
                rows = page.locator('#contentForm\\:tbParadas_data tr.ui-datatable-selectable')
                page.wait_for_function(
                    "document.querySelectorAll('#contentForm\\\\:tbParadas_data tr.ui-datatable-selectable').length > 0", 
                    timeout=15000
                )
                
                # PASO 2: Filtrado
                print(f"[PW] Escribiendo parada {stop_id}...")
                filter_input = page.locator('input.filtroBusquedaW25').first
                filter_input.wait_for(state='visible', timeout=10000)
                filter_input.fill('')
                filter_input.type(stop_id, delay=150)
                
                # Forzar búsqueda: Enter + Espera corta
                page.keyboard.press('Enter')
                page.wait_for_timeout(3000) # Tiempo para que la tabla mermé
                
                # PASO 3: Clic en la primera fila resultante (tras el filtro solo debería quedar una)
                print("[PW] Fila encontrada. Seleccionando...")
                target_rows = page.locator('#contentForm\\:tbParadas_data tr.ui-datatable-selectable')
                
                if target_rows.count() == 0:
                    print("[PW] Error: No quedó ninguna fila tras filtrar. Reintentando clic genérico...")
                    # Fallback por si el ID no es exactamente el texto pero la fila está ahí
                    target_row = page.locator('#contentForm\\:tbParadas_data tr').nth(0)
                else:
                    target_row = target_rows.first

                target_row.click()
                
                # PASO 4: Extraer la tabla de Tiempos
                # Esperamos a que la tabla de TIEMPOS tenga contenido real (no solo el mensaje de carga)
                print("[PW] Esperando estimaciones reales...")
                page.wait_for_selector('#contentForm\\:tbTiemposParadas_data tr', state='visible', timeout=15000)
                
                # Truco: Esperar a que la primera celda tenga texto (evita leer tablas vacias en transicion)
                try:
                    page.wait_for_function(
                        "document.querySelector('#contentForm\\\\:tbTiemposParadas_data td') && document.querySelector('#contentForm\\\\:tbTiemposParadas_data td').innerText.length > 0",
                        timeout=8000
                    )
                except:
                    pass # Si falla, intentamos leer lo que haya anyway

                buses = []
                # Forzamos una pequeña pausa de cortesia para el AJAX
                page.wait_for_timeout(1000)
                
                time_rows = page.locator('#contentForm\\:tbTiemposParadas_data tr').all()

                for row in time_rows:
                    cells_text = row.locator('td').all_inner_texts()
                    if len(cells_text) >= 3:
                        lin = cells_text[0].strip()
                        it = cells_text[1].strip()
                        mins = cells_text[2].strip()
                        
                        # Validar que sea un bus real (Nombre de linea corto, tiempo con 'm' o 'min')
                        if lin and len(lin) < 15 and ('No ' not in lin) and ('se han' not in it):
                            buses.append({'linea': lin, 'itinerario': it, 'minutos': mins})

                print(f"[PW] ✅ {len(buses)} buses extraídos con éxito.")
                return {'parada': stop_id, 'buses': buses, 'success': True}

            except Exception as e:
                print(f"[PW] Error: {e}")
                return {'parada': stop_id, 'buses': [], 'error': str(e), 'success': False}
            finally:
                browser.close()
