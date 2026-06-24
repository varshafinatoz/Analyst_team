import sys
import requests
import pandas as pd
import numpy as np
from datetime import date, timedelta

RISK_FREE_RATE = 0.053  # 5.3% annual (91-day treasury bill)


def get_last_business_day_of_prev_month():
    today = date.today()
    last = today.replace(day=1) - timedelta(days=1)
    while last.weekday() >= 5:
        last -= timedelta(days=1)
    return last


def search_fund(query):
    resp = requests.get(f"https://api.mfapi.in/mf/search?q={query}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_nav_data(scheme_code):
    resp = requests.get(f"https://api.mfapi.in/mf/{scheme_code}", timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    df = pd.DataFrame(payload["data"])
    df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y")
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    df = df.dropna(subset=["nav"]).sort_values("date").reset_index(drop=True)
    return df, payload["meta"]


def to_monthly_nav(df):
    """Pick the last available NAV for each calendar month (end-of-month NAV)."""
    df = df.copy()
    df["ym"] = df["date"].dt.to_period("M")
    monthly = df.groupby("ym").last().reset_index()
    return monthly


def nearest_nav(df, target):
    subset = df[df["date"] <= pd.Timestamp(target)]
    return float(subset.iloc[-1]["nav"]) if not subset.empty else None


def cagr(nav_start, nav_end, years):
    if nav_start is None or nav_end is None:
        return None
    return (nav_end / nav_start) ** (1 / years) - 1


def annualised_volatility_monthly(monthly_df, start, end):
    """Annualised volatility from monthly returns (Value Research / Morningstar standard)."""
    mask = (monthly_df["date"] >= pd.Timestamp(start)) & (monthly_df["date"] <= pd.Timestamp(end))
    window = monthly_df[mask]["nav"].pct_change().dropna()
    return float(window.std() * np.sqrt(12)) if len(window) >= 2 else None


def sharpe(ret, vol, rfr=RISK_FREE_RATE):
    if ret is None or vol is None or vol == 0:
        return None
    return (ret - rfr) / vol


def fmt_pct(val):
    return f"{val * 100:.2f}%" if val is not None else "N/A"


def fmt_num(val):
    return f"{val:.4f}" if val is not None else "N/A"


def analyze(query, risk_free_rate=RISK_FREE_RATE):
    # Resolve scheme code
    try:
        scheme_code = int(query)
    except ValueError:
        results = search_fund(query)
        if not results:
            print(f"No funds found for '{query}'.")
            return
        scheme_code = results[0]["schemeCode"]
        print(f"Matched: {results[0]['schemeName']}  (code {scheme_code})")
        if len(results) > 1:
            print(f"  (+ {len(results) - 1} other match(es) — using top result)")

    df, meta = get_nav_data(scheme_code)
    monthly_df = to_monthly_nav(df)

    print(f"\nFund      : {meta.get('scheme_name', 'N/A')}")
    print(f"Category  : {meta.get('scheme_category', 'N/A')}")
    print(f"Fund House: {meta.get('fund_house', 'N/A')}")

    base = get_last_business_day_of_prev_month()
    nav_base = nearest_nav(df, base)
    if nav_base is None:
        print("Could not retrieve base NAV.")
        return

    print(f"\nBase date : {base.strftime('%d %b %Y')}  |  Base NAV: {nav_base:.4f}")
    print(f"Methodology: Monthly NAV returns, Vol = std × √12  (Value Research / Morningstar standard)")

    results_table = {}
    for years in (3, 5):
        try:
            start = base.replace(year=base.year - years)
        except ValueError:
            start = base - timedelta(days=365 * years)

        nav_start = nearest_nav(df, start)
        r = cagr(nav_start, nav_base, years)
        v = annualised_volatility_monthly(monthly_df, start, base)
        s = sharpe(r, v, risk_free_rate)
        results_table[years] = (r, v, s)

    print(f"\n{'Metric':<26} {'3-Year':>12} {'5-Year':>12}")
    print("-" * 52)
    print(f"{'CAGR':<26} {fmt_pct(results_table[3][0]):>12} {fmt_pct(results_table[5][0]):>12}")
    print(f"{'Volatility (Ann.)':<26} {fmt_pct(results_table[3][1]):>12} {fmt_pct(results_table[5][1]):>12}")
    print(f"{'Sharpe Ratio':<26} {fmt_num(results_table[3][2]):>12} {fmt_num(results_table[5][2]):>12}")


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Enter fund name or scheme code: ").strip()
    analyze(query)
