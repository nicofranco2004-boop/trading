"""¿Cuántos CEDEARs hacen una acción de AstraZeneca (AZN) y de Bioceres (BIOX)? (06/11/2026)

La tabla de ratios (`frontend/src/utils/cedearRatio.js` y su copia
`backend/ratios_cedear.py`) decía AZN = 2, copiado de la lista de Comafi. La
medición del CEDEAR estimado (medir_cedear_estimado.out) dio, contra el cierre de
BYMA, AZN +89 % y BIOX −25 %. Esto mide, con datos reales y sin la base de Rendi:

  1. AZN y BIOX: «acción de Nueva York × dólar ÷ CEDEAR en BYMA» día por día del
     último año, con el CCL (el dólar con que se pagan los CEDEARs) y con el MEP.
  2. AZN alrededor del 02/02/2026, el día que AstraZeneca canjeó su ADR (media
     acción) por la acción: Yahoo lo anota como un split de 0,5 y ajusta la
     historia. Con el precio CRUDO, antes del canje Nueva York cotizaba el ADR.
  3. ¿El AZN de Yahoo es la acción entera? Londres (AZN.L, en peniques) × libra/dólar.
  4. Lo que pagó cada CEDEAR de AZN en 2026 según BYMA → el ratio que implica.

Fuentes: Yahoo (yfinance), data912 (cierres de BYMA), argentinadatos (MEP y CCL).
Corre con (red; desde la raíz del repo):
  YF_TZ_CACHE_LOCATION=$(mktemp -d) python3 audit/_scripts/verificar_ratio_azn_biox.py \\
      > audit/_scripts/verificar_ratio_azn_biox.out
"""
import bisect
import os
import statistics
import warnings

import requests

warnings.filterwarnings("ignore")
import yfinance as yf  # noqa: E402

if os.environ.get("YF_TZ_CACHE_LOCATION"):
    yf.set_tz_cache_location(os.environ["YF_TZ_CACHE_LOCATION"])

DESDE, HASTA = "2025-06-01", "2026-11-07"
CANJE = "2026-02-02"

# Lo pagado por CEDEAR de AZN (pesos), de los avisos de BYMA tal como los publica
# stockanalysis.com/quote/bcba/AZN/dividend/ (consultado el 06/11/2026):
# (corte, pago, pesos por CEDEAR).
PAGOS_BYMA = [("2026-02-20", "2026-03-23", 682.79549), ("2026-08-07", "2026-09-08", 358.06461)]


def yahoo(ticker):
    tk = yf.Ticker(ticker)
    h = tk.history(start=DESDE, end=HASTA, auto_adjust=False, actions=True)
    return ({str(k.date()): float(r["Close"]) for k, r in h.iterrows()},
            {str(k.date()): float(v) for k, v in tk.splits.items()},
            {str(k.date()): float(v) for k, v in tk.dividends.items()})


def byma(papel):
    r = requests.get(f"https://data912.com/historical/cedears/{papel}", timeout=30)
    return {f["date"]: (f["c"], f.get("v") or 0) for f in r.json()}


def dolar(casa):
    r = requests.get(f"https://api.argentinadatos.com/v1/cotizaciones/dolares/{casa}", timeout=30)
    return {f["fecha"]: f["venta"] for f in r.json() if f.get("venta")}


def el_del_dia(serie, fecha):
    """El último valor publicado hasta `fecha` (el dólar no se publica todos los días)."""
    fechas = sorted(serie)
    i = bisect.bisect_right(fechas, fecha) - 1
    return serie[fechas[i]] if i >= 0 else None


def resumen(papel, ny, ba, ccl, mep, tabla):
    fechas = [f for f in sorted(ba) if f in ny]
    con_ccl = [ny[f] * el_del_dia(ccl, f) / ba[f][0] for f in fechas]
    con_mep = [ny[f] * el_del_dia(mep, f) / ba[f][0] for f in fechas]
    orden = sorted(con_ccl)
    lejos = [(f, round(r, 2)) for f, r in zip(fechas, con_ccl) if abs(r / tabla - 1) > 0.10]
    print(f"  {papel}: {len(fechas)} ruedas en común, {fechas[0]} a {fechas[-1]}")
    print(f"    con el CCL: mediana {statistics.median(con_ccl):.3f} "
          f"(el 80 % de los días entre {orden[len(orden) // 10]:.3f} y {orden[9 * len(orden) // 10]:.3f})")
    print(f"    con el MEP: mediana {statistics.median(con_mep):.3f}")
    print(f"    días a más de 10 % de {tabla:g}: {len(lejos)} {lejos}")
    por_mes = {}
    for f, r in zip(fechas, con_ccl):
        por_mes.setdefault(f[:7], []).append(r)
    print("    mediana por mes (CCL): " + " · ".join(f"{m[2:]} {statistics.median(x):.2f}"
                                                   for m, x in sorted(por_mes.items())))
    return fechas


def main():
    ccl, mep = dolar("contadoconliqui"), dolar("bolsa")
    azn, azn_splits, _ = yahoo("AZN")
    biox, _, _ = yahoo("BIOX")
    londres, _, londres_div = yahoo("AZN.L")
    libra, _, _ = yahoo("GBPUSD=X")
    ba_azn, ba_biox = byma("AZN"), byma("BIOX")

    print("## 1. Cuántos CEDEARs hacen una acción de Nueva York, día por día")
    resumen("AZN", azn, ba_azn, ccl, mep, 4)
    resumen("BIOX", biox, ba_biox, ccl, mep, 1)
    print("    BIOX, las últimas 6 ruedas (BYMA en pesos, Nueva York en US$, cociente con el CCL):")
    for f in [f for f in sorted(ba_biox) if f in biox][-6:]:
        print(f"      {f}: BYMA {ba_biox[f][0]:7.1f} · NY {biox[f]:.4f} · {biox[f] * el_del_dia(ccl, f) / ba_biox[f][0]:.3f}")

    print()
    print(f"## 2. AZN alrededor del canje ({CANJE}). Splits que anota Yahoo desde 2024: "
          f"{ {f: v for f, v in azn_splits.items() if f >= '2024'} }")
    print("   (antes del canje, el precio crudo de Nueva York es el ajustado × 0,5: el ADR)")
    for f in [f for f in sorted(ba_azn) if f in azn and "2026-01-20" <= f <= "2026-02-10"]:
        crudo = azn[f] * 0.5 if f < CANJE else azn[f]
        c = el_del_dia(ccl, f)
        print(f"   {f}: BYMA {ba_azn[f][0]:8.0f} · NY ajustado {azn[f]:7.2f} · crudo {crudo:7.2f} · "
              f"CEDEARs por acción {azn[f] * c / ba_azn[f][0]:.2f} · por lo que cotizaba ese día {crudo * c / ba_azn[f][0]:.2f}")

    print()
    print("## 3. ¿El AZN de Yahoo es la acción entera? Londres en US$ ÷ AZN de Nueva York")
    pares = [(f, londres[f] / 100 * libra[f] / azn[f]) for f in sorted(azn) if f in londres and f in libra]
    for f, r in pares[:: max(1, len(pares) // 6)] + pares[-1:]:
        print(f"   {f}: {r:.3f}")

    print()
    print("## 4. Lo pagado por CEDEAR de AZN (BYMA) → cuántos CEDEARs por acción implica")
    for corte, pago, pesos in PAGOS_BYMA:
        # El dividendo por acción en US$: el de Londres (peniques, corte un día antes
        # que en BYMA) × libra/dólar de ese día.
        ex_londres = max(f for f in londres_div if f <= corte)
        usd_accion = londres_div[ex_londres] / 100 * el_del_dia(libra, ex_londres)
        for casa, serie in (("MEP", mep), ("CCL", ccl)):
            usd_cedear = pesos / el_del_dia(serie, pago)
            print(f"   corte {corte}, pago {pago}: $ {pesos:.2f} por CEDEAR = US$ {usd_cedear:.4f} con el {casa} "
                  f"del pago; la acción pagó US$ {usd_accion:.3f} → {usd_accion / usd_cedear:.2f} CEDEARs por acción"
                  f" (lo cobrado sería {usd_cedear * 4 / usd_accion:.0%} del bruto con 4, "
                  f"{usd_cedear * 2 / usd_accion:.0%} con 2)")
    print("   (AstraZeneca es del Reino Unido, que no retiene impuesto: lo cobrado es el bruto menos comisiones)")


if __name__ == "__main__":
    main()
