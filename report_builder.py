# ============================================================
# MID Ops Report Bot — Report Builder
# ============================================================
# Formats query results into Telegram markdown text + HTML for PNG screenshots.

from datetime import datetime, timedelta
from config import NUTRA_ADJ_AR_THRESHOLD, XSHIELD_ADJ_AR_THRESHOLD, THIN_VOLUME_THRESHOLD
from routing_state import load_state, format_active_mids, format_recent_changes, get_active_mid_names


def calc_adj_ar(sales, declines, hard_declines):
    """Calculate Adjusted AR%. Excludes soft declines from denominator."""
    soft = declines - hard_declines
    adj_denominator = sales + hard_declines
    if adj_denominator == 0:
        return None
    return (sales / adj_denominator) * 100


def calc_raw_ar(sales, declines):
    """Calculate Raw AR%."""
    total = sales + declines
    if total == 0:
        return None
    return (sales / total) * 100


def format_ar(value, threshold, total_txns):
    """Format AR% with bold if below threshold and * if thin volume."""
    if value is None:
        text = "—"
    else:
        text = f"{value:.1f}%"
    if total_txns < THIN_VOLUME_THRESHOLD:
        text += "*"
    return text, (value is not None and value < threshold)


# ============================================================
# NUTRA REPORT BUILDER
# ============================================================

def build_nutra_report(perf_data, amex_data, decline_data, window_label, utc_label):
    """
    Build complete Nutra report.
    Returns: (telegram_text, html_for_screenshot, analysis_text)
    """
    state = load_state()
    visa_active = get_active_mid_names("visa", state)
    mc_active = get_active_mid_names("mc", state)

    # Separate Visa v1 and MC v2
    visa_rows = []
    mc_rows = []

    for row in perf_data:
        mid = row["mid_name"]
        cc = row["card_cc_type"]
        sales = row["sales"]
        dec = row["declines"]
        hard = row["hard_declines"]

        is_v2 = mid.lower().endswith("_v2")

        # Visa = v1 MIDs with visa card type
        if cc == "visa" and not is_v2:
            visa_rows.append({"mid": mid, "sales": sales, "declines": dec, "hard_declines": hard})
        # MC = v2 MIDs with master card type
        elif cc == "master" and is_v2:
            mc_rows.append({"mid": mid, "sales": sales, "declines": dec, "hard_declines": hard})
        # Non-pool traffic (visa on v2, master on v1, etc.) — still include
        elif cc == "visa" and is_v2:
            visa_rows.append({"mid": mid, "sales": sales, "declines": dec, "hard_declines": hard})
        elif cc == "master" and not is_v2:
            # Skip master on v1 MIDs for the main Visa table
            pass

    # Build tables
    visa_table = _build_mid_table(visa_rows, "visa", visa_active, NUTRA_ADJ_AR_THRESHOLD)
    mc_table = _build_mid_table(mc_rows, "mc", mc_active, NUTRA_ADJ_AR_THRESHOLD)

    # AMEX footnote
    amex_sales = amex_data.get("sales", 0)
    amex_dec = amex_data.get("declines", 0)
    amex_note = f"AMEX footnote: {amex_sales} sale(s), {amex_dec} decline(s)."
    if amex_sales == 0 and amex_dec == 0:
        amex_note += " No AMEX volume this window."
    else:
        amex_note += " Excluded from main table."

    # Telegram text
    tg_text = f"*Mint (Nutra) MID Report — {window_label}*\n"
    tg_text += f"Window: {window_label} ({utc_label})\n\n"
    tg_text += "📊 *MID Performance — Visa (v1 MIDs)*\n"
    tg_text += visa_table["text"]
    tg_text += f"\n{format_active_mids('visa', state)}\n\n{format_recent_changes('visa', state)}\n"
    tg_text += f"\n_{amex_note}_\n\n"
    tg_text += "📊 *MID Performance — MC (v2 MIDs)*\n"
    tg_text += mc_table["text"]
    tg_text += f"\n{format_active_mids('mc', state)}\n\n{format_recent_changes('mc', state)}\n"

    # HTML for screenshot
    html = _build_nutra_html(visa_table, mc_table, visa_active, mc_active,
                              amex_note, window_label, utc_label, state)

    return tg_text, html


def _build_mid_table(rows, brand, active_mids, threshold):
    """Build a MID performance table from row data."""
    total_sales = sum(r["sales"] for r in rows)
    total_dec = sum(r["declines"] for r in rows)
    total_hard = sum(r["hard_declines"] for r in rows)

    table_rows = []
    for r in rows:
        mid = r["mid"]
        s = r["sales"]
        d = r["declines"]
        h = r["hard_declines"]
        total = s + d

        adj = calc_adj_ar(s, d, h)
        raw = calc_raw_ar(s, d)

        adj_str, adj_bold = format_ar(adj, threshold, total)
        raw_str, raw_bold = format_ar(raw, threshold, total)

        # Check if this MID is in the active pool
        is_active = any(mid.startswith(a) or mid == a for a in active_mids)

        table_rows.append({
            "mid": mid, "sales": s, "declines": d,
            "adj_str": adj_str, "adj_bold": adj_bold,
            "raw_str": raw_str, "raw_bold": raw_bold,
            "is_active": is_active
        })

    # Total row
    total_total = total_sales + total_dec
    total_adj = calc_adj_ar(total_sales, total_dec, total_hard)
    total_raw = calc_raw_ar(total_sales, total_dec)
    total_adj_str, total_adj_bold = format_ar(total_adj, threshold, total_total)
    total_raw_str, total_raw_bold = format_ar(total_raw, threshold, total_total)

    # Build text version
    lines = []
    for r in table_rows:
        mid_display = f"**{r['mid']}**" if r["is_active"] else r["mid"]
        adj = f"**{r['adj_str']}**" if r["adj_bold"] else r["adj_str"]
        raw = f"**{r['raw_str']}**" if r["raw_bold"] else r["raw_str"]
        lines.append(f"{mid_display} | {r['sales']} | {r['declines']} | {adj} | {raw}")

    total_adj_display = f"**{total_adj_str}**" if total_adj_bold else total_adj_str
    total_raw_display = f"**{total_raw_str}**" if total_raw_bold else total_raw_str
    lines.append(f"**TOTAL** | **{total_sales}** | **{total_dec}** | {total_adj_display} | {total_raw_display}")

    text = "MID | Sales | Dec | Adj. AR% | Raw AR%\n"
    text += "---|---|---|---|---\n"
    text += "\n".join(lines)

    return {
        "text": text,
        "rows": table_rows,
        "total": {
            "sales": total_sales, "declines": total_dec,
            "adj_str": total_adj_str, "adj_bold": total_adj_bold,
            "raw_str": total_raw_str, "raw_bold": total_raw_bold
        }
    }


def _build_nutra_html(visa_table, mc_table, visa_active, mc_active,
                       amex_note, window_label, utc_label, state):
    """Build HTML for Nutra report screenshot (no analysis section)."""

    def make_table_html(table_data, active_mids):
        rows_html = ""
        for r in table_data["rows"]:
            mid_class = ' class="active-mid"' if r["is_active"] else ""
            adj_class = ' class="bold-val"' if r["adj_bold"] else ""
            raw_class = ' class="bold-val"' if r["raw_bold"] else ""
            rows_html += f'    <tr><td{mid_class}>{r["mid"]}</td><td>{r["sales"]}</td><td>{r["declines"]}</td><td{adj_class}>{r["adj_str"]}</td><td{raw_class}>{r["raw_str"]}</td></tr>\n'

        t = table_data["total"]
        tadj_class = ' class="bold-val"' if t["adj_bold"] else ""
        traw_class = ' class="bold-val"' if t["raw_bold"] else ""
        rows_html += f'    <tr><td>TOTAL</td><td>{t["sales"]}</td><td>{t["declines"]}</td><td{tadj_class}>{t["adj_str"]}</td><td{traw_class}>{t["raw_str"]}</td></tr>\n'
        return rows_html

    visa_rows_html = make_table_html(visa_table, visa_active)
    mc_rows_html = make_table_html(mc_table, mc_active)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; background: #fff; color: #1a1a1a; padding: 40px 48px; max-width: 780px; line-height: 1.5; }}
  h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 6px; font-style: italic; }}
  .window {{ font-size: 14px; color: #444; margin-bottom: 28px; }}
  h2 {{ font-size: 17px; font-weight: 700; margin-bottom: 14px; margin-top: 36px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; font-size: 14px; }}
  thead th {{ text-align: left; font-weight: 700; font-size: 13px; padding: 8px 12px; border-bottom: 1.5px solid #222; }}
  thead th:not(:first-child) {{ text-align: center; }}
  tbody td {{ padding: 10px 12px; border-bottom: 1px solid #e5e5e5; }}
  tbody td:not(:first-child) {{ text-align: center; }}
  tbody tr:last-child td {{ border-bottom: 1.5px solid #222; font-weight: 700; }}
  .bold-val {{ font-weight: 700; }}
  .active-mid {{ font-weight: 700; }}
  .active-mids {{ margin-top: 24px; font-size: 14px; }}
  .active-mids strong {{ font-weight: 700; }}
  .recent-changes {{ margin-top: 12px; font-size: 14px; }}
  .recent-changes strong {{ font-weight: 700; }}
  .footnote {{ margin-top: 16px; padding-left: 16px; border-left: 3px solid #ddd; font-size: 13px; font-style: italic; color: #666; }}
</style>
</head>
<body>
<h1>Mint (Nutra) MID Report — {window_label}</h1>
<div class="window">Window: {window_label} ({utc_label})</div>

<h2>MID Performance — Visa (v1 MIDs)</h2>
<table>
  <thead><tr><th>MID</th><th>Sales</th><th>Dec</th><th>Adj. AR%</th><th>Raw AR%</th></tr></thead>
  <tbody>
{visa_rows_html}  </tbody>
</table>
<div class="active-mids"><strong>Active MIDs:</strong> {', '.join(f'{m} — {w}%' for m, w in state['visa']['active_mids'].items())}</div>
<div class="recent-changes"><strong>Recent Changes:</strong> {state['visa']['recent_changes']}</div>
<div class="footnote">{amex_note}</div>

<h2>MID Performance — MC (v2 MIDs)</h2>
<table>
  <thead><tr><th>MID</th><th>Sales</th><th>Dec</th><th>Adj. AR%</th><th>Raw AR%</th></tr></thead>
  <tbody>
{mc_rows_html}  </tbody>
</table>
<div class="active-mids"><strong>Active MIDs:</strong> {', '.join(f'{m} — {w}%' for m, w in state['mc']['active_mids'].items())}</div>
<div class="recent-changes"><strong>Recent Changes:</strong> {state['mc']['recent_changes']}</div>
</body>
</html>"""
    return html


# ============================================================
# XSHIELD REPORT BUILDER
# ============================================================

def build_xshield_report(perf_data, decline_data, amex_today, amex_yesterday,
                          window_label, utc_label, today_date, yesterday_date):
    """
    Build complete xShield report.
    Returns: (telegram_text, html_for_screenshot)
    """
    state = load_state()
    threshold = XSHIELD_ADJ_AR_THRESHOLD

    # Parse performance data into today/yesterday by card brand
    perf = {"Today": {}, "Yesterday": {}}
    for row in perf_data:
        day = row["day_label"]
        cc = row["card_cc_type"]
        if day and cc in ("visa", "master"):
            perf[day][cc] = row

    # Build performance rows
    def get_perf(day, cc):
        if cc in perf.get(day, {}):
            r = perf[day][cc]
            s, d, h = r["sales"], r["declines"], r["hard_declines"]
            total = s + d
            adj = calc_adj_ar(s, d, h)
            raw = calc_raw_ar(s, d)
            adj_str, adj_bold = format_ar(adj, threshold, total)
            raw_str, raw_bold = format_ar(raw, threshold, total)
            return s, d, adj_str, adj_bold, raw_str, raw_bold
        return 0, 0, "—*", False, "—*", False

    y_vs, y_vd, y_vadj, y_vadj_b, y_vraw, y_vraw_b = get_perf("Yesterday", "visa")
    y_ms, y_md, y_madj, y_madj_b, y_mraw, y_mraw_b = get_perf("Yesterday", "master")
    t_vs, t_vd, t_vadj, t_vadj_b, t_vraw, t_vraw_b = get_perf("Today", "visa")
    t_ms, t_md, t_madj, t_madj_b, t_mraw, t_mraw_b = get_perf("Today", "master")

    # AMEX footnote
    amex_note = f"AMEX footnote: Yesterday — {amex_yesterday.get('sales',0)} sale(s), {amex_yesterday.get('declines',0)} decline(s). Today — {amex_today.get('sales',0)} sale(s), {amex_today.get('declines',0)} decline(s). Excluded from main table."

    # Decline table
    decline_rows = []
    visa_total = 0
    mc_total = 0
    for row in decline_data:
        cc = row["card_cc_type"]
        reason = row["response_message"]
        cnt = row["cnt"]
        brand = "Visa" if cc == "visa" else "MC"
        decline_rows.append({"brand": brand, "reason": reason, "count": cnt})
        if cc == "visa":
            visa_total += cnt
        else:
            mc_total += cnt

    # Build HTML
    html = _build_xshield_html(
        y_vs, y_vd, y_vadj, y_vadj_b, y_vraw, y_vraw_b,
        y_ms, y_md, y_madj, y_madj_b, y_mraw, y_mraw_b,
        t_vs, t_vd, t_vadj, t_vadj_b, t_vraw, t_vraw_b,
        t_ms, t_md, t_madj, t_madj_b, t_mraw, t_mraw_b,
        amex_note, decline_rows, visa_total, mc_total,
        window_label, utc_label, today_date, yesterday_date, state
    )

    # Telegram text (simplified)
    tg_text = f"📊 *xShield MID Report — TY_6_Xshield*\n"
    tg_text += f"Window: {window_label} ({utc_label} | Today = {today_date}, Yesterday = {yesterday_date})\n\n"
    tg_text += f"Yesterday: V {y_vs}s/{y_vd}d ({y_vadj} Adj) | MC {y_ms}s/{y_md}d ({y_madj} Adj)\n"
    tg_text += f"Today: V {t_vs}s/{t_vd}d ({t_vadj} Adj) | MC {t_ms}s/{t_md}d ({t_madj} Adj)\n"

    return tg_text, html


def _build_xshield_html(y_vs, y_vd, y_vadj, y_vadj_b, y_vraw, y_vraw_b,
                          y_ms, y_md, y_madj, y_madj_b, y_mraw, y_mraw_b,
                          t_vs, t_vd, t_vadj, t_vadj_b, t_vraw, t_vraw_b,
                          t_ms, t_md, t_madj, t_madj_b, t_mraw, t_mraw_b,
                          amex_note, decline_rows, visa_total, mc_total,
                          window_label, utc_label, today_date, yesterday_date, state):
    """Build HTML for xShield screenshot (no analysis)."""

    def bv(val, bold):
        return f'<td class="bold-val">{val}</td>' if bold else f"<td>{val}</td>"

    # Decline rows HTML
    dec_html = ""
    visa_done = False
    for r in decline_rows:
        if r["brand"] == "MC" and not visa_done:
            dec_html += f'    <tr class="total-row"><td><strong>Visa Total</strong></td><td></td><td><strong>{visa_total}</strong></td></tr>\n'
            visa_done = True
        dec_html += f'    <tr><td>{r["brand"]}</td><td>{r["reason"]}</td><td>{r["count"]}</td></tr>\n'

    if not visa_done and visa_total > 0:
        dec_html += f'    <tr class="total-row"><td><strong>Visa Total</strong></td><td></td><td><strong>{visa_total}</strong></td></tr>\n'
    if mc_total > 0:
        dec_html += f'    <tr class="total-row"><td><strong>MC Total</strong></td><td></td><td><strong>{mc_total}</strong></td></tr>\n'

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; background: #fff; color: #1a1a1a; padding: 40px 48px; max-width: 900px; line-height: 1.5; }}
  h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 6px; }}
  .window {{ font-size: 14px; color: #444; margin-bottom: 28px; }}
  h2 {{ font-size: 17px; font-weight: 700; margin-bottom: 14px; margin-top: 36px; }}
  h3 {{ font-size: 15px; font-weight: 700; margin-bottom: 10px; margin-top: 28px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; font-size: 14px; }}
  thead th {{ text-align: left; font-weight: 700; font-size: 13px; padding: 8px 10px; border-bottom: 1.5px solid #222; }}
  thead th:not(:first-child) {{ text-align: center; }}
  tbody td {{ padding: 10px 10px; border-bottom: 1px solid #e5e5e5; }}
  tbody td:not(:first-child) {{ text-align: center; }}
  .total-row td {{ border-bottom: 1.5px solid #222; font-weight: 700; }}
  .bold-val {{ font-weight: 700; }}
  .active-mids {{ margin-top: 24px; font-size: 14px; }}
  .active-mids strong {{ font-weight: 700; }}
  .recent-changes {{ margin-top: 12px; font-size: 14px; }}
  .recent-changes strong {{ font-weight: 700; }}
  .footnote {{ margin-top: 16px; padding-left: 16px; border-left: 3px solid #ddd; font-size: 13px; font-style: italic; color: #666; }}
</style>
</head>
<body>
<h1>📊 xShield MID Report — TY_6_Xshield</h1>
<div class="window">Window: {window_label} ({utc_label} | Today = {today_date}, Yesterday = {yesterday_date})</div>

<h2>MID Performance</h2>
<table>
  <thead><tr><th>Date</th><th>Visa Sales</th><th>Visa Dec</th><th>Visa Adj. AR%</th><th>Visa Raw AR%</th><th>MC Sales</th><th>MC Dec</th><th>MC Adj. AR%</th><th>MC Raw AR%</th></tr></thead>
  <tbody>
    <tr><td>Yesterday</td><td>{y_vs}</td><td>{y_vd}</td>{bv(y_vadj, y_vadj_b)}{bv(y_vraw, y_vraw_b)}<td>{y_ms}</td><td>{y_md}</td>{bv(y_madj, y_madj_b)}{bv(y_mraw, y_mraw_b)}</tr>
    <tr><td>Today</td><td>{t_vs}</td><td>{t_vd}</td>{bv(t_vadj, t_vadj_b)}{bv(t_vraw, t_vraw_b)}<td>{t_ms}</td><td>{t_md}</td>{bv(t_madj, t_madj_b)}{bv(t_mraw, t_mraw_b)}</tr>
  </tbody>
</table>
<div class="active-mids"><strong>Active MID:</strong> TY_6_Xshield (single MID)</div>
<div class="recent-changes"><strong>Recent Changes:</strong> {state['xshield']['recent_changes']}</div>
<div class="footnote">{amex_note}</div>

<h2>Top Decline Reasons — TY_6_Xshield</h2>
<h3>Today ({today_date}) — {window_label.split(',')[-1].strip() if ',' in window_label else window_label}</h3>
<table>
  <thead><tr><th>Card Brand</th><th>Decline Reason</th><th>Count</th></tr></thead>
  <tbody>
{dec_html}  </tbody>
</table>
</body>
</html>"""
    return html
