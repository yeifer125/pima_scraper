import asyncio
import os
import json
import threading
import time
from datetime import datetime
from collections import OrderedDict
from flask import Flask, Response
from playwright.async_api import async_playwright
import pdfplumber

# ---------------- Rutas de archivos ----------------
PDF_FOLDER = os.path.join(os.path.dirname(__file__), "pdfs")
CACHE_FILE = os.path.join(os.path.dirname(__file__), "datos_cache.json")

# ---------------- Funciones PDF/Web ----------------
async def auto_scroll(page):
    await page.evaluate("""
        async () => {
            await new Promise(resolve => {
                let totalHeight = 0;
                const distance = 100;
                const timer = setInterval(() => {
                    const scrollHeight = document.body.scrollHeight;
                    window.scrollBy(0, distance);
                    totalHeight += distance;
                    if(totalHeight >= scrollHeight){
                        clearInterval(timer);
                        resolve();
                    }
                }, 100);
            });
        }
    """)

async def extraer_documentos(page_or_frame):
    return await page_or_frame.eval_on_selector_all(
        "a",
        """
        anchors => anchors
            .filter(a => a.innerText.includes('Documentos adjuntos'))
            .map(a => ({texto: a.innerText.trim(), href: a.href}))
        """
    )

async def descargar_archivo(context, url, nombre):
    os.makedirs(PDF_FOLDER, exist_ok=True)
    ruta_archivo = os.path.join(PDF_FOLDER, nombre)
    if os.path.exists(ruta_archivo):
        return ruta_archivo
    response = await context.request.get(url)
    if response.ok:
        contenido = await response.body()
        with open(ruta_archivo, "wb") as f:
            f.write(contenido)
        return ruta_archivo
    return None

# ---------------- Función corregida para extraer productos ----------------
def extraer_todo_pdf(ruta_pdf):
    resultados = []
    fecha = ""
    with pdfplumber.open(ruta_pdf) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text()
            if not texto:
                continue
            for linea in texto.split("\n"):
                linea_lower = linea.lower()
                if "fecha de plaza" in linea_lower:
                    parts = linea.split(":")
                    if len(parts) > 1:
                        fecha = parts[1].strip()

                columnas = linea.split()
                if len(columnas) < 5:  # mínimo producto + unidad + 4 valores
                    continue

                # Últimos 4 elementos → valores numéricos
                valores = columnas[-4:]
                try:
                    minimo = float(valores[0].replace(",", ""))
                    maximo = float(valores[1].replace(",", ""))
                    moda = float(valores[2].replace(",", ""))
                    promedio = float(valores[3].replace(",", ""))
                except ValueError:
                    continue

                # Elemento anterior → unidad/mayorista
                mayorista = columnas[-5]

                # Todo lo que queda al inicio → nombre del producto
                prod_nombre = " ".join(columnas[:-5])

                if not prod_nombre.strip() or prod_nombre.lower().startswith("producto"):
                    continue

                resultados.append(OrderedDict([
                    ("producto", prod_nombre),
                    ("unidad", mayorista),
                    ("mayorista", mayorista),
                    ("minimo", str(minimo)),
                    ("maximo", str(maximo)),
                    ("moda", str(moda)),
                    ("promedio", str(promedio)),
                    ("fecha", fecha)
                ]))
    return resultados

# ---------------- Corregir orden por fecha ----------------
def parse_fecha(fecha_str):
    try:
        return datetime.strptime(fecha_str, "%d/%m/%Y")
    except:
        return datetime.min

# ---------------- Función principal de scraping ----------------
async def main_scraping():
    rutas_pdfs = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://www.pima.go.cr/boletin/", wait_until="networkidle")
        await auto_scroll(page)

        documentos = []
        documentos.extend(await extraer_documentos(page))
        for frame in page.frames:
            documentos.extend(await extraer_documentos(frame))

        documentos = [dict(t) for t in {tuple(d.items()) for d in documentos}]

        for i, doc in enumerate(documentos, 1):
            nombre = f"{i}_{doc['texto'][:20].replace(' ', '_')}.pdf"
            ruta_pdf = await descargar_archivo(context, doc['href'], nombre)
            if ruta_pdf:
                rutas_pdfs.append(ruta_pdf)

        await browser.close()

    todos_resultados = []
    for pdf_path in rutas_pdfs:
        resultados = extraer_todo_pdf(pdf_path)
        todos_resultados.extend(resultados)

    todos_resultados.sort(key=lambda x: parse_fecha(x["fecha"]), reverse=True)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(todos_resultados, f, ensure_ascii=False, indent=2)

    print(f"[{datetime.now()}] Datos actualizados: {len(todos_resultados)} productos guardados en '{CACHE_FILE}'.")

# ---------------- Tarea periódica cada 24h ----------------
def tarea_periodica():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        try:
            loop.run_until_complete(main_scraping())
        except Exception as e:
            print(f"[ERROR] Falló la actualización: {e}")
        time.sleep(24 * 60 * 60)

# ---------------- API Flask ----------------
app = Flask(__name__)

@app.route("/")
def index():
    return "API PIMA funcionando. Usa /precios para ver los datos."

@app.route("/precios", methods=["GET"])
def obtener_precios():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            datos = json.load(f)
        return Response(json.dumps(datos, ensure_ascii=False, indent=2), mimetype="application/json")
    else:
        return Response(json.dumps({"error": "No existe el archivo de cache"}, ensure_ascii=False), mimetype="application/json"), 404

# ---------------- Ejecutar ----------------
if __name__ == "__main__":
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main_scraping())
    except Exception as e:
        print(f"[ERROR] Falló la actualización inicial: {e}")

    threading.Thread(target=tarea_periodica, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
