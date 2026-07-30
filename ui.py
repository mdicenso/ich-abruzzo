"""Componenti UI di ICH — stile "Console" allineato a TDH (cfr. tdhlib.py).

Perché così: gli stili sono INLINE sugli elementi HTML → si renderizzano sempre
(a differenza dei blocchi <style>, che Streamlit >=1.58 scarta). Palette e misure
prese dal cruscotto TDH per uniformità tra i due gestionali.
"""
from __future__ import annotations
import streamlit as st

# Palette (identica a TDH)
INK = "#10262a"; MUTED = "#5c7176"; FAINT = "#8aa0a4"; LINE = "#e4ebec"
SLATE = "#0f172a"; SLATE_M = "#64748b"; SLATE_F = "#94a3b8"; TEAL = "#0e6b70"


def page_header(title: str, subtitle: str = "", group: str = ""):
    """Header di pagina: breadcrumb maiuscoletto + titolo grande + filetto."""
    crumb = f"{group} &nbsp;›&nbsp; {title}" if group else title
    sub = (f"<div style='font-size:.86rem;color:{MUTED};margin-top:5px;max-width:920px'>{subtitle}</div>"
           if subtitle else "")
    st.markdown(f"""
    <div style="margin:.1rem 0 1rem;padding-bottom:.7rem;border-bottom:1px solid {LINE}">
      <div style="font-size:.68rem;letter-spacing:.12em;text-transform:uppercase;color:{FAINT};font-weight:600">{crumb}</div>
      <div style="font-size:1.5rem;font-weight:700;letter-spacing:-.02em;line-height:1.15;color:{INK};margin-top:6px">{title}</div>
      {sub}
    </div>""", unsafe_allow_html=True)


def section_header(title: str, subtitle: str = "", icon: str = ""):
    """Intestazione di sezione con filetto — sostituisce st.markdown('### ...')."""
    ic = f"<span style='font-size:1.2rem'>{icon}</span>" if icon else ""
    sub = (f"<div style='font-size:.8rem;color:{SLATE_M};margin-top:1px'>{subtitle}</div>"
           if subtitle else "")
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:10px;margin:1.4rem 0 .6rem;
                padding-bottom:.6rem;border-bottom:1px solid #e2e8f0">
      {ic}<div><div style="font-size:1.05rem;font-weight:700;color:{SLATE}">{title}</div>{sub}</div>
    </div>""", unsafe_allow_html=True)


def kpi_row(items: list[dict]):
    """Riga di KPI 'executive'. items: [{label, value, delta?, delta_dir?('up'|'down'|'flat'), hint?}]."""
    for col, it in zip(st.columns(len(items)), items):
        dh = ""
        if it.get("delta"):
            d = it.get("delta_dir", "flat")
            color = {"up": "#16a34a", "down": "#dc2626", "flat": "#64748b"}.get(d, "#64748b")
            arrow = {"up": "▲", "down": "▼", "flat": "→"}.get(d, "")
            dh = (f"<div style='font-size:.8rem;font-weight:700;color:{color};margin-top:6px'>"
                  f"{arrow} {it['delta']}</div>")
        hint = (f"<div style='font-size:.72rem;color:{FAINT};margin-top:4px'>{it['hint']}</div>"
                if it.get("hint") else "")
        col.markdown(f"""
        <div style="background:#fff;border:1px solid {LINE};border-radius:14px;padding:16px 18px;height:100%">
          <div style="font-size:.72rem;font-weight:600;color:{MUTED};text-transform:uppercase;letter-spacing:.05em">{it['label']}</div>
          <div style="font-size:1.9rem;font-weight:700;color:{INK};line-height:1.1;margin-top:7px;
                      font-variant-numeric:tabular-nums">{it['value']}</div>
          {dh}{hint}
        </div>""", unsafe_allow_html=True)


def badge(text: str, color: str = TEAL) -> str:
    """Pill colorata (ritorna HTML, da usare dentro una card)."""
    return (f"<span style='background:{color}1f;color:{color};padding:3px 11px;border-radius:999px;"
            f"font-size:.8rem;font-weight:600;white-space:nowrap'>{text}</span>")


def card(title: str, body_html: str = "", top: str = ""):
    """Card bianca con ombra morbida (per elenchi/schede)."""
    topbar = f"<div style='font-size:.8rem;color:{SLATE_F};font-weight:700'>{top}</div>" if top else ""
    st.markdown(f"""
    <div style="background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:16px 18px;
                box-shadow:0 1px 3px rgba(15,23,42,.06);margin-bottom:.6rem">
      {topbar}
      <div style="font-size:1.12rem;font-weight:700;color:{SLATE};margin:2px 0 8px">{title}</div>
      <div style="color:{SLATE_M};font-size:.9rem">{body_html}</div>
    </div>""", unsafe_allow_html=True)


def aggrid_table(df, height: int = 340, key: str | None = None):
    """Tabella interattiva (st_aggrid) con fallback a st.dataframe se non installato."""
    try:
        from st_aggrid import AgGrid, GridOptionsBuilder
        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_default_column(resizable=True, sortable=True, filter=True)
        AgGrid(df, gridOptions=gb.build(), height=height,
               fit_columns_on_grid_load=True, theme="balham", key=key)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True)
