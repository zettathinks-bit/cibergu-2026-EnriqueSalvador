import requests
from bs4 import BeautifulSoup
import re
import json
import time

class GuadalajaraStopsDownloader:
    def __init__(self):
        self.base_url = "http://urbanos.guadalajara.es/tiempos/tiemposParada.xhtml"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36"
        })

    def get_initial_viewstate(self):
        print("[*] Conectando con la web de urbanos...")
        response = self.session.get(self.base_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        viewstate = soup.find('input', dict(name="javax.faces.ViewState"))
        if viewstate:
            return viewstate['value']
        return None

    def fetch_all_stops(self):
        viewstate = self.get_initial_viewstate()
        if not viewstate:
            print("[!] No se pudo obtener el ViewState.")
            return []

        all_stops = []
        
        # PrimeFaces DataTable pagination logic
        # Intentamos obtener la primera página y ver cuántas hay o simplemente iterar
        # La tabla se llama contentForm:tbParadas
        # El parámetro contentForm:tbParadas_first indica el índice inicial
        
        page = 0
        rows_per_page = 5
        
        while True:
            print(f"[*] Descargando página {page + 1}...")
            
            payload = {
                "javax.faces.partial.ajax": "true",
                "javax.faces.source": "contentForm:tbParadas",
                "javax.faces.partial.execute": "contentForm:tbParadas",
                "javax.faces.partial.render": "contentForm:tbParadas",
                "contentForm:tbParadas": "contentForm:tbParadas",
                "contentForm:tbParadas_pagination": "true",
                "contentForm:tbParadas_first": str(page * rows_per_page),
                "contentForm:tbParadas_rows": str(rows_per_page),
                "contentForm": "contentForm",
                "javax.faces.ViewState": viewstate
            }
            
            headers_post = {
                "Faces-Request": "partial/ajax",
                "Referer": self.base_url
            }
            response = self.session.post(self.base_url, data=payload, headers=headers_post)
            
            # Extraer el HTML de la respuesta AJAX
            html_part = re.search(r'<!\[CDATA\[(.*?)\]\]>', response.text, re.DOTALL)
            if not html_part:
                print(f"[DEBUG] No hay CDATA. Respuesta: {response.text[:500]}")
                break
                
            soup = BeautifulSoup(html_part.group(1), 'html.parser')
            rows = soup.select('tr')
            
            if not rows or "No se han encontrado" in rows[0].get_text():
                print(f"[DEBUG] No hay rows reales. HTML: {html_part.group(1)[:500]}")
                break
                
            current_page_stops = 0
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 2:
                    stop_id = cells[0].get_text(strip=True)
                    stop_name = cells[1].get_text(strip=True)
                    print(f"  -> Viendo fila: ID='{stop_id}', NOMBRE='{stop_name}'")
                    if stop_id.isdigit():
                        all_stops.append({
                            "id": stop_id,
                            "nombre": stop_name
                        })
                        current_page_stops += 1
            
            if current_page_stops == 0:
                break
                
            page += 1
            time.sleep(0.5) # Respeto al servidor

        print(f"[+] ¡Éxito! Se han encontrado {len(all_stops)} paradas.")
        return all_stops

if __name__ == "__main__":
    downloader = GuadalajaraStopsDownloader()
    stops = downloader.fetch_all_stops()
    
    if stops:
        with open("paradas_guadalajara.json", "w", encoding="utf-8") as f:
            json.dump(stops, f, indent=4, ensure_ascii=False)
        print("[*] Datos guardados en paradas_guadalajara.json")
