from flask import Flask, request, render_template, send_file, redirect, url_for
import pandas as pd
import pyodbc
from io import BytesIO
import zipfile

app = Flask(__name__)

archivo_en_memoria = None  # Archivo limpio completo
archivos_en_memoria = {}  # Archivos separados por operador en memoria

def obtener_lista_negra():
    conexion = pyodbc.connect(
        'DRIVER={ODBC Driver 17 for SQL Server};'
        'SERVER=192.168.1.15;'
        'DATABASE=BD_CR_MAESTRA;'
        'UID=powerbi;'
        'PWD=Aa123456'
    )
    cursor = conexion.cursor()
    cursor.execute("SELECT TELEFONO FROM BD_CR_MAESTRA.dbo.RS_V_BLACKLIST_CANALESDIGITALES")
    telefonos = [str(row[0]) for row in cursor.fetchall()]
    cursor.close()
    conexion.close()
    return telefonos

@app.route("/", methods=["GET", "POST"])
def index():
    global archivo_en_memoria, archivos_en_memoria
    resumen = None
    conteo_operadores = None
    archivos_en_memoria = {}

    if request.method == "POST":
        archivo = request.files.get("archivo")
        if archivo:
            df = pd.read_excel(archivo)

            if df.empty or df.shape[1] < 4:
                resumen = {"error": "El archivo está vacío o no contiene al menos 4 columnas."}
            else:
                # Formatear columnas 1 y 3 como texto
                df.iloc[:, 0] = df.iloc[:, 0].astype(str)
                df.iloc[:, 2] = df.iloc[:, 2].astype(str)

                lista_negra = obtener_lista_negra()

                # Filtrar filas donde la primera columna esté en lista negra
                mask_negra = df.iloc[:, 0].isin(lista_negra)
                df_filtrado = df[~mask_negra].copy()

                # Reemplazar cualquier variante de "sin operador" por "ENTEL"
                df_filtrado.iloc[:, 3] = df_filtrado.iloc[:, 3].apply(
                    lambda x: 'ENTEL' if isinstance(x, str) and 'sin operador' in x.lower() else x
                )

                # Estandarizar operadores a mayúsculas para el conteo
                df_filtrado.iloc[:, 3] = df_filtrado.iloc[:, 3].astype(str).str.upper()
                conteo = df_filtrado.iloc[:, 3].value_counts()

                # Identificar operadores principales y agrupar "OTRAS OPERADORAS"
                operadores_principales = ['CLARO', 'ENTEL', 'MOVISTAR']
                conteo_operadores = {}
                total_otras = 0
                for operador, cantidad in conteo.items():
                    if operador in operadores_principales:
                        conteo_operadores[operador] = cantidad
                    else:
                        total_otras += cantidad
                if total_otras > 0:
                    conteo_operadores['OTRAS OPERADORAS'] = total_otras

                # Guardar archivo limpio completo en memoria (solo columnas 0,1,2)
                archivo_en_memoria = BytesIO()
                with pd.ExcelWriter(archivo_en_memoria, engine='openpyxl') as writer:
                    df_filtrado.iloc[:, 0:3].to_excel(writer, index=False, sheet_name='Limpio')
                    ws = writer.sheets['Limpio']
                    for cell in ws['A']:
                        cell.number_format = '@'  # Formato texto columna A
                    for cell in ws['C']:
                        cell.number_format = '@'  # Formato texto columna C
                archivo_en_memoria.seek(0)

                # Crear archivos separados para cada operador (solo columnas 0,1,2)
                for operador in conteo_operadores.keys():
                    if operador == 'OTRAS OPERADORAS':
                        otros_df = df_filtrado[~df_filtrado.iloc[:, 3].isin(operadores_principales)]
                        df_op = otros_df.iloc[:, 0:3].copy()
                    else:
                        df_op = df_filtrado[df_filtrado.iloc[:, 3] == operador].iloc[:, 0:3].copy()

                    bio = BytesIO()
                    with pd.ExcelWriter(bio, engine='openpyxl') as writer:
                        df_op.to_excel(writer, index=False, sheet_name='Limpio')
                        ws = writer.sheets['Limpio']
                        for cell in ws['A']:
                            cell.number_format = '@'
                        for cell in ws['C']:
                            cell.number_format = '@'
                    bio.seek(0)
                    archivos_en_memoria[operador] = bio

                resumen = {
                    "total": len(df),
                    "en_negra": mask_negra.sum(),
                    "final": len(df_filtrado),
                    "procesado": True
                }

    return render_template("index.html", resumen=resumen, conteo_operadores=conteo_operadores)

@app.route("/descargar")
def descargar():
    global archivo_en_memoria
    if archivo_en_memoria:
        return send_file(archivo_en_memoria, as_attachment=True, download_name="excel_limpio.xlsx")
    return redirect(url_for("index"))

@app.route("/descargar_operador/<operador>")
def descargar_operador(operador):
    global archivos_en_memoria
    operador = operador.upper()
    if operador in archivos_en_memoria:
        archivo = archivos_en_memoria[operador]
        archivo.seek(0)
        return send_file(
            archivo,
            as_attachment=True,
            download_name=f"{operador}_limpio.xlsx"
        )
    return redirect(url_for("index"))

@app.route("/descargar_todos_operadores")
def descargar_todos_operadores():
    global archivos_en_memoria
    if not archivos_en_memoria:
        return redirect(url_for("index"))

    zip_mem = BytesIO()
    with zipfile.ZipFile(zip_mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zipf:
        for operador, archivo in archivos_en_memoria.items():
            archivo.seek(0)
            zipf.writestr(f"{operador}_limpio.xlsx", archivo.read())
    zip_mem.seek(0)

    return send_file(
        zip_mem,
        as_attachment=True,
        download_name="todos_operadores.zip",
        mimetype="application/zip"
    )

if __name__ == "__main__":
    app.run(debug=True)
