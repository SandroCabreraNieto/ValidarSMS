from flask import Flask, request, render_template, send_file, redirect, url_for, jsonify
import pandas as pd
import pyodbc
from io import BytesIO

app = Flask(__name__)

archivo_en_memoria = None
archivos_por_chip = {}
conteo_operadores_global = None
chips_inputs_global = {}
resumen_global = None
conteo_completo_global = None
lista_negra_df_global = pd.DataFrame()

chips_df = pd.read_csv("chips.csv")
chips_por_operador = chips_df.groupby("Operador")["Chip"].apply(list).to_dict()

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
    global archivo_en_memoria, archivos_por_chip
    global conteo_operadores_global, chips_inputs_global, resumen_global
    global lista_negra_df_global, conteo_completo_global

    resumen = None
    conteo_operadores = None
    conteo_completo = None
    chips_inputs = {}

    if request.method == "POST":
        archivo = request.files.get("archivo")
        if archivo:
            df = pd.read_excel(archivo)

            if df.empty or df.shape[1] < 4:
                resumen = {"error": "El archivo está vacío o no contiene al menos 4 columnas."}
                resumen_global = resumen
            else:
                df.iloc[:, 0] = df.iloc[:, 0].astype(str)
                df.iloc[:, 2] = df.iloc[:, 2].astype(str)
                lista_negra = obtener_lista_negra()
                mask_negra = df.iloc[:, 0].isin(lista_negra)

                lista_negra_df = df[mask_negra].copy()
                lista_negra_df_global = lista_negra_df

                df_filtrado = df[~mask_negra].copy()
                df_filtrado['OPERADOR_ORIGINAL'] = df_filtrado.iloc[:, 3].astype(str).str.upper()
                df_filtrado['OPERADOR_AGRUPADO'] = df_filtrado['OPERADOR_ORIGINAL'].apply(
                    lambda x: 'ENTEL' if 'SIN OPERADOR' in x else x
                )

                conteo_completo = df_filtrado['OPERADOR_ORIGINAL'].value_counts().to_dict()
                conteo_completo_global = conteo_completo

                conteo = df_filtrado['OPERADOR_AGRUPADO'].value_counts()
                operadores_principales = ['CLARO', 'ENTEL', 'MOVISTAR']
                conteo_operadores = {op: conteo[op] for op in operadores_principales if op in conteo}

                archivo_en_memoria = df_filtrado
                chips_inputs = {op: chips_por_operador.get(op.capitalize(), []) for op in conteo_operadores.keys()}

                conteo_operadores_global = conteo_operadores
                chips_inputs_global = chips_inputs

                resumen = {
                    "total": len(df),
                    "en_negra": mask_negra.sum(),
                    "final": len(df_filtrado),
                    "procesado": True
                }
                resumen_global = resumen

    return render_template(
        "index.html",
        resumen=resumen if resumen else resumen_global,
        conteo_operadores=conteo_operadores if conteo_operadores else conteo_operadores_global,
        conteo_completo=conteo_completo if conteo_completo else conteo_completo_global,
        chips_por_operador=chips_inputs if chips_inputs else chips_inputs_global,
        archivos_por_chip=archivos_por_chip,
        mostrar_modal=bool(not lista_negra_df_global.empty)
    )

@app.route("/dividir_chips", methods=["POST"])
def dividir_chips():
    global archivo_en_memoria, archivos_por_chip
    if archivo_en_memoria is None:
        return redirect(url_for("index"))

    df = archivo_en_memoria.copy()
    archivos_por_chip = {}

    operadores = df['OPERADOR_AGRUPADO'].unique()

    for operador in operadores:
        operador_df = df[df['OPERADOR_AGRUPADO'] == operador]
        chips_disponibles = chips_por_operador.get(operador.capitalize(), [])
        if not operador_df.empty and chips_disponibles:
            for chip in chips_disponibles:
                cantidad_key = f"cantidad_{operador}_{chip}"
                cantidad_str = request.form.get(cantidad_key)
                if not cantidad_str or not cantidad_str.strip().isdigit():
                    continue

                cantidad = int(cantidad_str)
                if cantidad <= 0:
                    continue

                df_chip = operador_df.iloc[:cantidad]
                operador_df = operador_df.drop(df_chip.index)
                df = df.drop(df_chip.index)

                bio = BytesIO()
                with pd.ExcelWriter(bio, engine='openpyxl') as writer:
                    df_chip.to_excel(writer, index=False, sheet_name='Limpio')
                bio.seek(0)
                archivos_por_chip[chip] = {
                    "archivo": bio,
                    "filas": len(df_chip)
                }

    return redirect(url_for("index"))

@app.route("/descargar_chip/<chip>")
def descargar_chip(chip):
    chip = chip.strip()
    if chip in archivos_por_chip:
        archivo = archivos_por_chip[chip]["archivo"]
        archivo.seek(0)
        return send_file(archivo, as_attachment=True, download_name=f"{chip}.xlsx")
    return redirect(url_for("index"))

@app.route("/lista_negra_data")
def lista_negra_data():
    global lista_negra_df_global
    if lista_negra_df_global.empty:
        return jsonify([])
    return lista_negra_df_global.to_dict(orient="records")

if __name__ == "__main__":
    app.run(debug=True, port=5001)
