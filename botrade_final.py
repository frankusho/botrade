import alpaca_trade_api as tradeapi
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json
import os
import time
import pytz
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# CONFIGURACION — EDITA SOLO ESTA SECCION
# ============================================================

TELEGRAM_TOKEN   = "8916752968:AAEKiOJ6Kmyy7A5sT_6gqYc1Tc42ULo0Lyk"
TELEGRAM_CHAT_ID = "6797033294"

ALPACA_KEY    = "PKSUYDBE7ZWYH5U6NWGML3FV72"
ALPACA_SECRET = "7Mr8tbrjkEDPbdtdAMF4NR83jDi8pUA5PCXZL8DLi1bC"
ALPACA_URL    = "https://paper-api.alpaca.markets"

NEWS_API_KEY = "ad535d6362b447528ab04ca93a7aa223"

# Google Sheets
SHEETS_ID        = "1vDYcAozml3v98ncEE-Ywglg7xRMH8D8gICpbiLMyC3k"
SHEETS_CREDS_FILE = "botrade-credentials.json"

ACTIVOS = [
    "AAPL",
    "SPY",
    "BTC-USD",
    "ETH-USD",
    "GOOGL",
    "TSLA",
]

CAPITAL_TOTAL       = 100000
KELLY_FRACCION      = 0.25
MAX_RIESGO          = 0.05
MIN_RIESGO          = 0.005
STOP_LOSS_PCT       = 0.05
TAKE_PROFIT_PCT     = 0.10
MAX_POSICIONES      = 3
CIRCUIT_BREAKER_PCT = 0.05
CAIDA_MERCADO_PCT   = 0.01
VOLUMEN_MINIMO_X    = 1.5
ESTADO_FILE         = "botrade_estado.json"

# ============================================================
# GOOGLE SHEETS
# ============================================================

def conectar_sheets():
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        # Intentar desde variable de entorno primero (Railway)
        google_creds_env = os.environ.get("GOOGLE_CREDENTIALS")
        if google_creds_env:
            import tempfile
            creds_dict = json.loads(google_creds_env)
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        else:
            # Fallback: leer desde archivo local
            creds = Credentials.from_service_account_file(SHEETS_CREDS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEETS_ID)
    except Exception as e:
        print(f"Error Google Sheets: {e}")
        return None

def inicializar_sheets():
    """Crea las pestañas y cabeceras si no existen"""
    print("Conectando a Google Sheets...")
    try:
        sh = conectar_sheets()
        if sh is None:
            print("✗ No se pudo conectar a Google Sheets")
            return
        print(f"✓ Google Sheets conectado: {sh.title}")

        # Pestaña DIARIO
        try:
            hoja_diario = sh.worksheet("Diario")
        except:
            hoja_diario = sh.add_worksheet(title="Diario", rows=1000, cols=10)
            hoja_diario.append_row([
                "Fecha", "Portafolio ($)", "Cash ($)", "P&L ($)",
                "Posiciones", "VIX", "Mercado", "Senales"
            ])
            print("✓ Hoja Diario creada")

        # Pestaña OPERACIONES
        try:
            hoja_ops = sh.worksheet("Operaciones")
        except:
            hoja_ops = sh.add_worksheet(title="Operaciones", rows=1000, cols=10)
            hoja_ops.append_row([
                "Fecha", "Tipo", "Ticker", "Precio ($)",
                "Acciones", "Inversion ($)", "P&L ($)", "Confianza (%)", "Kelly (%)"
            ])
            print("✓ Hoja Operaciones creada")

        # Pestaña METRICAS
        try:
            hoja_met = sh.worksheet("Metricas")
        except:
            hoja_met = sh.add_worksheet(title="Metricas", rows=1000, cols=10)
            hoja_met.append_row([
                "Fecha", "Ticker", "Calidad", "Sharpe",
                "Win Rate (%)", "Retorno (%)", "Max DD (%)", "Profit Factor", "Operaciones"
            ])
            print("✓ Hoja Metricas creada")

        # Pestaña SEÑALES
        try:
            hoja_sen = sh.worksheet("Senales")
        except:
            hoja_sen = sh.add_worksheet(title="Senales", rows=1000, cols=10)
            hoja_sen.append_row([
                "Fecha", "Ticker", "Señal", "Precio ($)",
                "RSI", "MACD", "Bollinger", "Sentimiento", "Confianza (%)"
            ])
            print("✓ Hoja Senales creada")

        print("✓ Google Sheets inicializado")
    except Exception as e:
        print(f"Error inicializar Sheets: {e}")

def sheets_registrar_diario(capital, cash, pnl, n_posiciones, vix, mercado, n_senales):
    try:
        sh = conectar_sheets()
        if sh is None:
            return
        hoja = sh.worksheet("Diario")
        hoja.append_row([
            datetime.now().strftime('%d/%m/%Y %H:%M'),
            round(capital, 2),
            round(cash, 2),
            round(pnl, 2),
            n_posiciones,
            vix,
            mercado,
            n_senales
        ])
        print("✓ Registro diario guardado en Sheets")
    except Exception as e:
        print(f"Error Sheets diario: {e}")

def sheets_registrar_operacion(tipo, ticker, precio, acciones, inversion, pnl, confianza, kelly):
    try:
        sh = conectar_sheets()
        if sh is None:
            return
        hoja = sh.worksheet("Operaciones")
        hoja.append_row([
            datetime.now().strftime('%d/%m/%Y %H:%M'),
            tipo,
            ticker,
            round(precio, 2),
            acciones,
            round(inversion, 2),
            round(pnl, 2),
            confianza,
            round(kelly * 100, 2)
        ])
        print(f"✓ Operacion {tipo} {ticker} guardada en Sheets")
    except Exception as e:
        print(f"Error Sheets operacion: {e}")

def sheets_registrar_metricas(resultados):
    try:
        sh = conectar_sheets()
        if sh is None:
            return
        hoja = sh.worksheet("Metricas")
        fecha = datetime.now().strftime('%d/%m/%Y')
        for r in resultados:
            hoja.append_row([
                fecha,
                r["ticker"],
                r["calidad"],
                r["sharpe"],
                r["win_rate"],
                r["retorno"],
                r["max_dd"],
                r["profit_factor"],
                r["operaciones"]
            ])
        print("✓ Metricas guardadas en Sheets")
    except Exception as e:
        print(f"Error Sheets metricas: {e}")

def sheets_registrar_senal(ticker, senal, precio, rsi, macd, bb, sentimiento, confianza):
    try:
        sh = conectar_sheets()
        if sh is None:
            return
        hoja = sh.worksheet("Senales")
        hoja.append_row([
            datetime.now().strftime('%d/%m/%Y %H:%M'),
            ticker,
            senal,
            round(precio, 2),
            rsi,
            macd,
            bb,
            sentimiento,
            confianza
        ])
    except Exception as e:
        print(f"Error Sheets senal: {e}")

# ============================================================
# TELEGRAM
# ============================================================

def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"})
    except Exception as e:
        print(f"Error Telegram: {e}")

def obtener_mensajes(offset=0):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=3"
        resp = requests.get(url, timeout=8).json()
        return resp.get("result", [])
    except:
        return []

def cargar_estado():
    try:
        if os.path.exists(ESTADO_FILE):
            with open(ESTADO_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {"activo": True, "ultimo_reporte_semanal": ""}

def guardar_estado(estado):
    try:
        with open(ESTADO_FILE, 'w') as f:
            json.dump(estado, f)
    except:
        pass

# ============================================================
# INDICADORES
# ============================================================

def calcularRSI(closes, periodo=14):
    gains = losses = 0
    for i in range(len(closes)-periodo, len(closes)):
        d = closes[i] - closes[i-1]
        if d > 0: gains += d
        else: losses -= d
    rs = (gains/periodo) / (losses/periodo or 0.001)
    return round(100 - 100/(1+rs), 1)

def calcularEMA(closes, periodo):
    k = 2/(periodo+1)
    ema = closes[0]
    for c in closes[1:]: ema = c*k + ema*(1-k)
    return round(ema, 2)

def calcularMACD(closes):
    return round(calcularEMA(closes,12) - calcularEMA(closes,26) - calcularEMA(closes,9), 4)

def calcularBollinger(closes, periodo=20):
    sl = closes[-periodo:]
    media = sum(sl)/periodo
    std = (sum((v-media)**2 for v in sl)/periodo)**0.5
    precio = closes[-1]
    rango = 4*std
    return round((precio-(media-2*std))/rango*100, 1) if rango > 0 else 50

def obtenerVIX():
    try:
        datos = yf.download("^VIX", period="5d", progress=False, auto_adjust=True)
        if isinstance(datos.columns, pd.MultiIndex):
            datos.columns = datos.columns.get_level_values(0)
        return round(float(datos["Close"].squeeze().dropna().iloc[-1]), 2)
    except:
        return 20

def analizarSentimiento(ticker):
    try:
        url = f"https://newsapi.org/v2/everything?q={ticker}+stock&language=en&sortBy=publishedAt&pageSize=5&apiKey={NEWS_API_KEY}"
        resp = requests.get(url).json()
        positivas = ['surge','soars','gains','rises','record','beats','strong','growth','profit','bullish','rally','upgrade','higher','boost','earnings']
        negativas = ['falls','drops','plunges','loses','weak','miss','bearish','lower','concern','loss','decline','crash','warning','downgrade','lawsuit']
        puntaje = 0
        for a in resp.get('articles', [])[:5]:
            texto = ((a.get('title','') or '') + ' ' + (a.get('description','') or '')).lower()
            for p in positivas:
                if p in texto: puntaje += 1
            for n in negativas:
                if n in texto: puntaje -= 1
        if puntaje >= 3: return 'MUY POSITIVO'
        if puntaje >= 1: return 'POSITIVO'
        if puntaje <= -3: return 'MUY NEGATIVO'
        if puntaje <= -1: return 'NEGATIVO'
        return 'NEUTRAL'
    except:
        return 'NEUTRAL'

# ============================================================
# KELLY AUTOMATICO
# ============================================================

def calcularKelly(ticker):
    try:
        datos = yf.download(ticker, period="2y", progress=False, auto_adjust=True)
        if isinstance(datos.columns, pd.MultiIndex):
            datos.columns = datos.columns.get_level_values(0)
        closes = [float(x) for x in datos["Close"].squeeze().dropna().tolist()]
        if len(closes) < 100:
            return MIN_RIESGO

        operaciones = []
        en_posicion = False
        precio_entrada = 0

        for i in range(50, len(closes)):
            precio = closes[i]
            rsi = calcularRSI(closes[:i+1])
            emaDiff = (calcularEMA(closes[:i+1],20) - calcularEMA(closes[:i+1],50)) / calcularEMA(closes[:i+1],50) * 100
            macd = calcularMACD(closes[:i+1])
            bb = calcularBollinger(closes[:i+1])

            vc = vv = 0
            if rsi < 35: vc += 2
            elif rsi > 65: vv += 2
            if emaDiff > 0.3: vc += 2
            elif emaDiff < -0.3: vv += 2
            if macd > 0: vc += 1
            else: vv += 1
            if bb < 20: vc += 1
            elif bb > 80: vv += 1

            senal = "COMPRAR" if vc >= 4 else "VENDER" if vv >= 4 else "MANTENER"

            if senal == "COMPRAR" and not en_posicion:
                precio_entrada = precio
                en_posicion = True
            elif senal == "VENDER" and en_posicion:
                cambio = (precio - precio_entrada) / precio_entrada
                operaciones.append(cambio)
                en_posicion = False

        if len(operaciones) < 3:
            return MIN_RIESGO

        ganadas = [r for r in operaciones if r > 0]
        perdidas = [r for r in operaciones if r <= 0]

        if not ganadas or not perdidas:
            return MIN_RIESGO

        win_rate     = len(ganadas) / len(operaciones)
        avg_ganancia = np.mean(ganadas)
        avg_perdida  = abs(np.mean(perdidas))
        ratio_gp     = avg_ganancia / avg_perdida if avg_perdida > 0 else 1

        kelly = (win_rate * ratio_gp - (1 - win_rate)) / ratio_gp
        return round(max(MIN_RIESGO, min(MAX_RIESGO, kelly * KELLY_FRACCION)), 4)
    except:
        return MIN_RIESGO

# ============================================================
# METRICAS SEMANALES AUTOMATICAS
# ============================================================

def calcularMetricasSemana():
    try:
        print("Calculando metricas semanales...")
        resultados = []

        for ticker in ACTIVOS:
            try:
                datos = yf.download(ticker, period="2y", progress=False, auto_adjust=True)
                if isinstance(datos.columns, pd.MultiIndex):
                    datos.columns = datos.columns.get_level_values(0)
                closes = [float(x) for x in datos["Close"].squeeze().dropna().tolist()]
                if len(closes) < 100:
                    continue

                capital = 10000
                capital_hist = [10000]
                operaciones = []
                en_posicion = False
                precio_entrada = 0

                for i in range(50, len(closes)):
                    precio = closes[i]
                    rsi = calcularRSI(closes[:i+1])
                    emaDiff = (calcularEMA(closes[:i+1],20) - calcularEMA(closes[:i+1],50)) / calcularEMA(closes[:i+1],50) * 100
                    macd = calcularMACD(closes[:i+1])
                    bb = calcularBollinger(closes[:i+1])

                    vc = vv = 0
                    if rsi < 35: vc += 2
                    elif rsi > 65: vv += 2
                    if emaDiff > 0.3: vc += 2
                    elif emaDiff < -0.3: vv += 2
                    if macd > 0: vc += 1
                    else: vv += 1
                    if bb < 20: vc += 1
                    elif bb > 80: vv += 1

                    senal = "COMPRAR" if vc >= 4 else "VENDER" if vv >= 4 else "MANTENER"

                    if senal == "COMPRAR" and not en_posicion:
                        precio_entrada = precio
                        en_posicion = True
                    elif en_posicion:
                        cambio = (precio - precio_entrada) / precio_entrada
                        if senal == "VENDER" or cambio <= -STOP_LOSS_PCT or cambio >= TAKE_PROFIT_PCT:
                            ganancia = 10000 * 0.02 * cambio
                            capital += ganancia
                            operaciones.append({"ganancia": ganancia, "cambio": cambio})
                            en_posicion = False
                    capital_hist.append(capital)

                if len(operaciones) < 2:
                    continue

                ganancias = [o["ganancia"] for o in operaciones]
                retornos  = [o["cambio"] for o in operaciones]
                ganadas   = [g for g in ganancias if g > 0]
                perdidas  = [g for g in ganancias if g < 0]

                win_rate      = round(len(ganadas)/len(operaciones)*100, 1)
                retorno_total = round((capital - 10000)/10000*100, 2)
                retornos_arr  = np.array(retornos)
                sharpe        = round(np.mean(retornos_arr)/(np.std(retornos_arr)+1e-10)*np.sqrt(252), 2)
                capital_arr   = np.array(capital_hist)
                pico          = np.maximum.accumulate(capital_arr)
                max_dd        = round(float(np.min((capital_arr-pico)/pico))*100, 2)
                profit_factor = round(sum(g for g in ganancias if g > 0) / abs(sum(g for g in ganancias if g < 0)), 2) if perdidas else 999

                calidad = "EXCELENTE" if sharpe >= 1 and profit_factor >= 1.5 else "BUENO" if sharpe >= 0.5 else "DEBIL"
                emoji   = "🟢" if calidad == "EXCELENTE" else "🟡" if calidad == "BUENO" else "🔴"

                resultados.append({
                    "ticker": ticker,
                    "emoji": emoji,
                    "calidad": calidad,
                    "retorno": retorno_total,
                    "sharpe": sharpe,
                    "max_dd": max_dd,
                    "win_rate": win_rate,
                    "profit_factor": profit_factor,
                    "operaciones": len(operaciones)
                })

            except:
                continue

        if not resultados:
            return

        resultados.sort(key=lambda x: x["sharpe"], reverse=True)

        msg = f"📈 <b>REPORTE SEMANAL DE METRICAS</b>\n━━━━━━━━━━━━━━━━━━\n"
        for r in resultados:
            msg += (
                f"\n{r['emoji']} <b>{r['ticker']}</b> — {r['calidad']}\n"
                f"  Sharpe: {r['sharpe']} | WR: {r['win_rate']}%\n"
                f"  Retorno: {r['retorno']}% | DD: {r['max_dd']}%\n"
                f"  PF: {r['profit_factor']} | Ops: {r['operaciones']}\n"
            )

        mejor = resultados[0]
        peor  = resultados[-1]
        msg += (
            f"\n━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Mejor: {mejor['ticker']} (Sharpe {mejor['sharpe']})\n"
            f"⚠️  Peor: {peor['ticker']} (Sharpe {peor['sharpe']})\n"
            f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )

        enviar_telegram(msg)
        print("✓ Reporte semanal enviado")

        # Guardar en Google Sheets
        sheets_registrar_metricas(resultados)

    except Exception as e:
        print(f"Error metricas: {e}")

def verificarReporteSemanal():
    estado = cargar_estado()
    hoy = datetime.now().strftime("%Y-%W")
    if estado.get("ultimo_reporte_semanal", "") != hoy:
        calcularMetricasSemana()
        estado["ultimo_reporte_semanal"] = hoy
        guardar_estado(estado)

# ============================================================
# SEGURIDAD
# ============================================================

def verificarCircuitBreaker(api):
    try:
        cuenta = api.get_account()
        capital_actual = float(cuenta.portfolio_value)
        caida = (CAPITAL_TOTAL - capital_actual) / CAPITAL_TOTAL
        if caida >= CIRCUIT_BREAKER_PCT:
            enviar_telegram(
                f"🚨 <b>CIRCUIT BREAKER</b>\n"
                f"📉 Caida: {round(caida*100,2)}%\n"
                f"💰 Capital: ${capital_actual:,.2f}\n"
                f"🛑 Bot detenido\n"
                f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            )
            return True
        return False
    except:
        return False

def verificarTendenciaMercado():
    try:
        datos = yf.download("SPY", period="5d", progress=False, auto_adjust=True)
        if isinstance(datos.columns, pd.MultiIndex):
            datos.columns = datos.columns.get_level_values(0)
        closes = datos["Close"].squeeze().dropna().tolist()
        cambio = (closes[-1] - closes[-2]) / closes[-2]
        if cambio <= -CAIDA_MERCADO_PCT:
            print(f"  ⚠️  Mercado cayendo {round(cambio*100,2)}%")
            return False
        return True
    except:
        return True

def verificarVolumen(ticker):
    try:
        datos = yf.download(ticker, period="1mo", progress=False, auto_adjust=True)
        if isinstance(datos.columns, pd.MultiIndex):
            datos.columns = datos.columns.get_level_values(0)
        vols = datos["Volume"].squeeze().dropna().tolist()
        ratio = vols[-1] / (sum(vols[:-1])/len(vols[:-1]))
        return round(ratio, 2), ratio >= VOLUMEN_MINIMO_X
    except:
        return 1.0, True

def verificarOrdenPendiente(api, ticker):
    try:
        return any(o.symbol == ticker for o in api.list_orders(status='open'))
    except:
        return False

# ============================================================
# ANALIZAR ACTIVO
# ============================================================

def analizarActivo(ticker):
    datos = yf.download(ticker, period="6mo", progress=False, auto_adjust=True)
    if isinstance(datos.columns, pd.MultiIndex):
        datos.columns = datos.columns.get_level_values(0)
    closes = [float(x) for x in datos["Close"].squeeze().dropna().tolist()]
    if len(closes) < 60:
        return None

    precio = closes[-1]
    cambio = round((precio - closes[-2]) / closes[-2] * 100, 2)
    rsi = calcularRSI(closes)
    emaDiff = round((calcularEMA(closes,20) - calcularEMA(closes,50)) / calcularEMA(closes,50) * 100, 3)
    macd = calcularMACD(closes)
    bb = calcularBollinger(closes)

    vc = vv = 0
    razones = []

    if rsi < 35: vc += 2; razones.append(f"RSI sobrevendido ({rsi})")
    elif rsi > 65: vv += 2; razones.append(f"RSI sobrecomprado ({rsi})")
    if emaDiff > 0.3: vc += 2; razones.append(f"EMA alcista (+{emaDiff}%)")
    elif emaDiff < -0.3: vv += 2; razones.append(f"EMA bajista ({emaDiff}%)")
    if macd > 0: vc += 1; razones.append(f"MACD positivo ({macd})")
    else: vv += 1; razones.append(f"MACD negativo ({macd})")
    if bb < 20: vc += 1; razones.append(f"Bollinger banda baja ({bb}%)")
    elif bb > 80: vv += 1; razones.append(f"Bollinger banda alta ({bb}%)")

    sentimiento = analizarSentimiento(ticker)
    razones.append(f"Noticias: {sentimiento}")
    if sentimiento == 'MUY POSITIVO': vc += 1
    elif sentimiento == 'POSITIVO': vc += 0.5
    elif sentimiento == 'MUY NEGATIVO': vv += 1
    elif sentimiento == 'NEGATIVO': vv += 0.5

    confianza = round(max(vc, vv) / 7 * 100)
    senal = "COMPRAR" if vc >= 4 else "VENDER" if vv >= 4 else "MANTENER"

    # Registrar señal en Sheets
    if senal != "MANTENER":
        sheets_registrar_senal(ticker, senal, precio, rsi, macd, bb, sentimiento, confianza)

    return {
        "ticker": ticker, "precio": round(precio, 2), "cambio": cambio,
        "rsi": rsi, "emaDiff": emaDiff, "macd": macd, "bb": bb,
        "sentimiento": sentimiento, "senal": senal, "confianza": confianza,
        "razones": razones, "votosCompra": vc, "votosVenta": vv
    }

# ============================================================
# EJECUTAR ORDEN
# ============================================================

def ejecutarOrden(api, resultado, vix, mercado_ok, kelly_pct):
    ticker = resultado["ticker"]
    senal  = resultado["senal"]
    precio = resultado["precio"]
    confianza = resultado["confianza"]

    try:
        posiciones   = {p.symbol: p for p in api.list_positions()}
        capital      = float(api.get_account().cash)
        n_posiciones = len(posiciones)

        if senal == "COMPRAR" and ticker not in posiciones:
            if verificarOrdenPendiente(api, ticker):
                return f"⚠️  Orden pendiente para {ticker}"
            if not mercado_ok:
                return "⚠️  Mercado cayendo — bloqueado"
            if n_posiciones >= MAX_POSICIONES:
                return f"⚠️  Max posiciones ({MAX_POSICIONES})"
            if vix > 30:
                return f"⚠️  VIX alto ({vix})"

            vol_ratio, vol_ok = verificarVolumen(ticker)
            if not vol_ok:
                return f"⚠️  Volumen bajo ({vol_ratio}x)"

            stop_precio = round(precio * (1 - STOP_LOSS_PCT), 2)
            acciones    = int((CAPITAL_TOTAL * kelly_pct) / (precio - stop_precio))

            if acciones > 0 and capital >= acciones * precio:
                api.submit_order(symbol=ticker, qty=acciones, side='buy', type='market', time_in_force='day')
                inversion = acciones * precio
                enviar_telegram(
                    f"🟢 <b>COMPRA EJECUTADA</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📈 Activo: <b>{ticker}</b>\n"
                    f"💵 Precio: ${precio:,.2f}\n"
                    f"📦 Acciones: {acciones}\n"
                    f"💰 Inversion: ${inversion:,.2f}\n"
                    f"🛑 Stop loss: ${stop_precio:,.2f}\n"
                    f"🎯 Take profit: ${round(precio*(1+TAKE_PROFIT_PCT),2):,.2f}\n"
                    f"🧮 Kelly: {round(kelly_pct*100,2)}%\n"
                    f"📊 Volumen: {vol_ratio}x\n"
                    f"🎲 Confianza: {confianza}%\n"
                    f"📰 Noticias: {resultado['sentimiento']}\n"
                    f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                )
                # Registrar en Sheets
                sheets_registrar_operacion("COMPRA", ticker, precio, acciones, inversion, 0, confianza, kelly_pct)
                return f"COMPRA: {acciones} acc | Kelly:{round(kelly_pct*100,1)}% | Vol:{vol_ratio}x"
            return "Capital insuficiente"

        elif senal == "VENDER" and ticker in posiciones:
            acciones = int(float(posiciones[ticker].qty))
            pnl      = float(posiciones[ticker].unrealized_pl)
            precio_entrada = float(posiciones[ticker].avg_entry_price)
            api.submit_order(symbol=ticker, qty=acciones, side='sell', type='market', time_in_force='day')
            emoji = "🟢" if pnl > 0 else "🔴"
            enviar_telegram(
                f"{emoji} <b>VENTA EJECUTADA</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📉 Activo: <b>{ticker}</b>\n"
                f"💵 Precio: ${precio:,.2f}\n"
                f"📦 Acciones: {acciones}\n"
                f"💰 P&L: ${pnl:,.2f}\n"
                f"🎲 Confianza: {confianza}%\n"
                f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            )
            # Registrar en Sheets
            sheets_registrar_operacion("VENTA", ticker, precio, acciones, acciones * precio_entrada, pnl, confianza, kelly_pct)
            return f"VENTA: {acciones} acc | P&L: ${pnl:.2f}"

        return "Sin accion"

    except Exception as e:
        return f"Error: {e}"

# ============================================================
# REPORTE DIARIO
# ============================================================

def reporteDiario(api, vix=20, mercado="FAVORABLE", n_senales=0):
    try:
        cuenta    = api.get_account()
        capital   = float(cuenta.portfolio_value)
        cash      = float(cuenta.cash)
        posiciones = api.list_positions()
        pnl_total = sum(float(p.unrealized_pl) for p in posiciones)
        emoji     = "🟢" if pnl_total >= 0 else "🔴"

        detalle = ""
        for p in posiciones:
            pnl     = float(p.unrealized_pl)
            pnl_pct = float(p.unrealized_plpc) * 100
            e = "🟢" if pnl >= 0 else "🔴"
            detalle += f"\n{e} {p.symbol}: {p.qty} acc | P&L: ${pnl:,.2f} ({pnl_pct:.1f}%)"

        if not detalle:
            detalle = "\nSin posiciones abiertas"

        enviar_telegram(
            f"📊 <b>REPORTE DIARIO</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Portafolio: ${capital:,.2f}\n"
            f"💵 Cash: ${cash:,.2f}\n"
            f"{emoji} P&L: ${pnl_total:,.2f}\n"
            f"📂 Posiciones: {len(posiciones)}\n"
            f"\n<b>Detalle:</b>{detalle}\n"
            f"\n⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
        print("✓ Reporte diario enviado")

        # Registrar en Google Sheets
        sheets_registrar_diario(capital, cash, pnl_total, len(posiciones), vix, mercado, n_senales)

    except Exception as e:
        print(f"Error reporte: {e}")

# ============================================================
# COMANDOS TELEGRAM
# ============================================================

def cmd_estado(api):
    try:
        cuenta    = api.get_account()
        posiciones = api.list_positions()
        pnl_total = sum(float(p.unrealized_pl) for p in posiciones)
        estado    = cargar_estado()
        status    = "✅ ACTIVO" if estado.get("activo", True) else "⏸ PAUSADO"
        emoji     = "🟢" if pnl_total >= 0 else "🔴"
        enviar_telegram(
            f"🤖 <b>ESTADO</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{status}\n"
            f"💰 Portafolio: ${float(cuenta.portfolio_value):,.2f}\n"
            f"💵 Cash: ${float(cuenta.cash):,.2f}\n"
            f"{emoji} P&L: ${pnl_total:,.2f}\n"
            f"📂 Posiciones: {len(posiciones)}\n"
            f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
    except Exception as e:
        enviar_telegram(f"❌ Error: {e}")

def cmd_posiciones(api):
    try:
        posiciones = api.list_positions()
        if not posiciones:
            enviar_telegram("📂 Sin posiciones abiertas.")
            return
        msg = "📂 <b>POSICIONES</b>\n━━━━━━━━━━━━━━━━━━\n"
        for p in posiciones:
            pnl     = float(p.unrealized_pl)
            pnl_pct = float(p.unrealized_plpc) * 100
            e = "🟢" if pnl >= 0 else "🔴"
            msg += (
                f"\n{e} <b>{p.symbol}</b>\n"
                f"  Acciones: {p.qty}\n"
                f"  Entrada: ${float(p.avg_entry_price):,.2f}\n"
                f"  Actual: ${float(p.current_price):,.2f}\n"
                f"  P&L: ${pnl:,.2f} ({pnl_pct:.1f}%)\n"
            )
        enviar_telegram(msg)
    except Exception as e:
        enviar_telegram(f"❌ Error: {e}")

def cmd_metricas():
    enviar_telegram("📊 Calculando metricas... esto tarda 2-3 minutos.")
    calcularMetricasSemana()

def cmd_pausar():
    estado = cargar_estado()
    estado["activo"] = False
    guardar_estado(estado)
    enviar_telegram("⏸ <b>Bot pausado.</b>\nUsa /reanudar para activarlo.")

def cmd_reanudar():
    estado = cargar_estado()
    estado["activo"] = True
    guardar_estado(estado)
    enviar_telegram("✅ <b>Bot reactivado.</b>")

def cmd_analizar(ticker, api):
    try:
        enviar_telegram(f"🔍 Analizando <b>{ticker}</b>...")
        resultado = analizarActivo(ticker)
        if resultado is None:
            enviar_telegram(f"❌ Sin datos para {ticker}")
            return
        kelly = calcularKelly(ticker)
        senal_emoji  = "🟢" if resultado['senal'] == "COMPRAR" else "🔴" if resultado['senal'] == "VENDER" else "🟡"
        cambio_emoji = "📈" if resultado['cambio'] >= 0 else "📉"
        enviar_telegram(
            f"🔍 <b>ANALISIS: {ticker}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{cambio_emoji} Precio: ${resultado['precio']:,.2f} ({resultado['cambio']:+.2f}%)\n"
            f"\n<b>Indicadores:</b>\n"
            f"  RSI: {resultado['rsi']}\n"
            f"  EMA: {resultado['emaDiff']:+.3f}%\n"
            f"  MACD: {resultado['macd']}\n"
            f"  Bollinger: {resultado['bb']}%\n"
            f"  Noticias: {resultado['sentimiento']}\n"
            f"\n{senal_emoji} <b>{resultado['senal']}</b> ({resultado['confianza']}%)\n"
            f"  Kelly: {round(kelly*100,2)}%\n"
            f"  Votos C/V: {resultado['votosCompra']}/{resultado['votosVenta']}\n"
            f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
    except Exception as e:
        enviar_telegram(f"❌ Error: {e}")

def cmd_ayuda():
    enviar_telegram(
        f"🤖 <b>BOTRADE v4.0</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"/estado — Estado y portafolio\n"
        f"/posiciones — Posiciones abiertas\n"
        f"/pausar — Pausar el bot\n"
        f"/reanudar — Reactivar el bot\n"
        f"/metricas — Ver metricas del sistema\n"
        f"/analizar TICKER — Analizar activo\n"
        f"  Ej: /analizar AAPL\n"
        f"  Ej: /analizar TSLA\n"
        f"  Ej: /analizar BTC-USD\n"
        f"/ayuda — Ver este menu\n"
        f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )

def procesarComandos(api, offset):
    mensajes = obtener_mensajes(offset)
    for msg in mensajes:
        offset = msg["update_id"] + 1
        if "message" not in msg:
            continue
        texto   = msg["message"].get("text", "").strip().lower()
        chat_id = str(msg["message"]["chat"]["id"])
        if chat_id != TELEGRAM_CHAT_ID:
            continue
        print(f"  Comando: {texto}")
        if texto == "/estado": cmd_estado(api)
        elif texto == "/posiciones": cmd_posiciones(api)
        elif texto == "/metricas": cmd_metricas()
        elif texto == "/pausar": cmd_pausar()
        elif texto == "/reanudar": cmd_reanudar()
        elif texto.startswith("/analizar"):
            partes = texto.split()
            if len(partes) >= 2:
                cmd_analizar(partes[1].upper(), api)
            else:
                enviar_telegram("❌ Uso: /analizar TICKER")
        elif texto in ["/ayuda", "/start"]:
            cmd_ayuda()
    return offset

# ============================================================
# ANALISIS PRINCIPAL
# ============================================================

def ejecutarAnalisis(api):
    estado = cargar_estado()
    if not estado.get("activo", True):
        print("Bot pausado")
        return

    ahora = datetime.now().strftime('%d/%m/%Y %H:%M')
    print(f"\n{'='*60}")
    print(f"BOTRADE v4.0 — {ahora}")
    print(f"{'='*60}")

    if verificarCircuitBreaker(api):
        print("🚨 CIRCUIT BREAKER")
        return

    vix          = obtenerVIX()
    estado_vix   = "PANICO" if vix > 35 else "MIEDO" if vix > 25 else "NORMAL" if vix > 15 else "TRANQUILO"
    mercado_ok   = verificarTendenciaMercado()
    estado_merc  = "FAVORABLE" if mercado_ok else "CAYENDO"
    capital      = float(api.get_account().portfolio_value)

    print(f"VIX: {vix} ({estado_vix}) | Mercado: {estado_merc}")
    print("Calculando Kelly...")

    kelly_activos = {}
    for ticker in ACTIVOS:
        k = calcularKelly(ticker)
        kelly_activos[ticker] = k
        print(f"  {ticker}: {round(k*100,2)}%")

    enviar_telegram(
        f"🤖 <b>BOTRADE v4.0</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 Activos: {len(ACTIVOS)}\n"
        f"😨 VIX: {vix} ({estado_vix})\n"
        f"📈 Mercado: {estado_merc}\n"
        f"💰 Portafolio: ${capital:,.2f}\n"
        f"⏰ {ahora}"
    )

    print("\nAnalizando activos...")
    print("-" * 60)
    senales = []

    for ticker in ACTIVOS:
        try:
            print(f"  {ticker}...", end=" ")
            r = analizarActivo(ticker)
            if r is None:
                print("sin datos")
                continue
            print(f"${r['precio']:.2f} | RSI:{r['rsi']} | {r['senal']} ({r['confianza']}%)")
            if r["senal"] != "MANTENER":
                senales.append(r)
                orden = ejecutarOrden(api, r, vix, mercado_ok, kelly_activos.get(ticker, MIN_RIESGO))
                print(f"    → {orden}")
        except Exception as e:
            print(f"Error: {e}")

    posiciones = api.list_positions()
    pnl_total  = sum(float(p.unrealized_pl) for p in posiciones)

    enviar_telegram(
        f"📋 <b>Resumen</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔍 Analizados: {len(ACTIVOS)}\n"
        f"⚡ Senales: {len(senales)}\n"
        f"📂 Posiciones: {len(posiciones)}\n"
        f"💰 P&L: ${pnl_total:,.2f}\n"
        f"⏰ {ahora}"
    )

    reporteDiario(api, vix, estado_merc, len(senales))
    verificarReporteSemanal()

# ============================================================
# MAIN
# ============================================================

# ============================================================
# HORARIO AUTOMATICO
# ============================================================

HORARIOS_ANALISIS = ["09:30", "13:00", "15:30"]
ZONA_HORARIA      = pytz.timezone("America/Santiago")

def hora_chile():
    return datetime.now(ZONA_HORARIA).strftime("%H:%M")

def fecha_chile():
    return datetime.now(ZONA_HORARIA).strftime("%Y-%m-%d")

def es_hora_analisis(analizados_hoy):
    hora = hora_chile()
    fecha = fecha_chile()
    for horario in HORARIOS_ANALISIS:
        clave = f"{fecha}_{horario}"
        if hora == horario and clave not in analizados_hoy:
            return True, clave
    return False, None

def monitorearStopLossTakeProfit(api):
    """Revisa posiciones abiertas y cierra si alcanzan stop loss o take profit"""
    try:
        posiciones = api.list_positions()
        if not posiciones:
            return

        for p in posiciones:
            ticker        = p.symbol
            pnl_pct       = float(p.unrealized_plpc) * 100
            precio_actual = float(p.current_price)
            precio_entrada= float(p.avg_entry_price)
            acciones      = int(float(p.qty))
            pnl           = float(p.unrealized_pl)

            cerrar = False
            razon  = ""

            if pnl_pct <= -STOP_LOSS_PCT * 100:
                cerrar = True
                razon  = f"🛑 STOP LOSS ({pnl_pct:.1f}%)"
            elif pnl_pct >= TAKE_PROFIT_PCT * 100:
                cerrar = True
                razon  = f"🎯 TAKE PROFIT ({pnl_pct:.1f}%)"

            if cerrar:
                try:
                    api.submit_order(
                        symbol=ticker,
                        qty=acciones,
                        side='sell',
                        type='market',
                        time_in_force='day'
                    )
                    emoji = "🟢" if pnl > 0 else "🔴"
                    enviar_telegram(
                        f"{emoji} <b>{razon}</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"📉 Activo: <b>{ticker}</b>\n"
                        f"💵 Entrada: ${precio_entrada:,.2f}\n"
                        f"💵 Salida: ${precio_actual:,.2f}\n"
                        f"📦 Acciones: {acciones}\n"
                        f"💰 P&L: ${pnl:,.2f} ({pnl_pct:.1f}%)\n"
                        f"⏰ {datetime.now(ZONA_HORARIA).strftime('%d/%m/%Y %H:%M')}"
                    )
                    sheets_registrar_operacion(
                        razon.split()[1], ticker, precio_actual,
                        acciones, acciones * precio_entrada, pnl, 100, 0
                    )
                    print(f"  {razon}: {ticker} | P&L: ${pnl:.2f}")
                except Exception as e:
                    print(f"Error cerrando {ticker}: {e}")

    except Exception as e:
        print(f"Error monitor SL/TP: {e}")
    print(f"\n{'='*60}")
    print(f"BOTRADE v4.0 — Sistema autonomo completo")
    print(f"{'='*60}")

    try:
        api    = tradeapi.REST(ALPACA_KEY, ALPACA_SECRET, ALPACA_URL, api_version='v2')
        cuenta = api.get_account()
        print(f"✓ Alpaca | ${float(cuenta.portfolio_value):,.2f}")
    except Exception as e:
        print(f"✗ Error Alpaca: {e}")
        return

    # Inicializar Google Sheets
    inicializar_sheets()

    enviar_telegram(
        f"🤖 <b>BOTRADE v4.0 activo</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Sistema autonomo iniciado.\n"
        f"📅 Análisis automático:\n"
        f"  • 09:30 AM — Apertura\n"
        f"  • 01:00 PM — Mediodía\n"
        f"  • 03:30 PM — Cierre\n"
        f"Escribe /ayuda para comandos.\n"
        f"⏰ {datetime.now(ZONA_HORARIA).strftime('%d/%m/%Y %H:%M')} (Chile)"
    )

    # Análisis inicial al arrancar
    ejecutarAnalisis(api)

    print(f"\nEscuchando comandos y horarios... (Ctrl+C para detener)")
    print(f"Análisis programado: {', '.join(HORARIOS_ANALISIS)} hora Chile")

    offset = 0
    analizados_hoy = set()
    ultimo_monitor = 0

    while True:
        try:
            # Verificar comandos Telegram
            offset = procesarComandos(api, offset)

            # Monitor Stop Loss / Take Profit cada 5 minutos
            ahora_ts = time.time()
            if ahora_ts - ultimo_monitor >= 300:
                monitorearStopLossTakeProfit(api)
                ultimo_monitor = ahora_ts

            # Verificar horario automático
            es_hora, clave = es_hora_analisis(analizados_hoy)
            if es_hora:
                print(f"\n⏰ Análisis programado: {hora_chile()}")
                analizados_hoy.add(clave)
                ejecutarAnalisis(api)

            time.sleep(30)  # Verificar cada 30 segundos

        except KeyboardInterrupt:
            print("\nBot detenido.")
            enviar_telegram("🛑 BOTRADE detenido.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()