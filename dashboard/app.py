"""
Web dashboard for the Africa security monitor (Streamlit) - dark
"intelligence platform" design.

Run it on your computer from the project folder:

    streamlit run dashboard/app.py

It opens in your browser at http://localhost:8501. It READS the official
database (data/monitor.db) and never changes it. Run `git pull` first to get
the latest data from GitHub.
"""

import json
import sqlite3
import unicodedata
from datetime import date, timedelta
from html import escape
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

DB_FILE = Path(__file__).resolve().parent.parent / "data" / "monitor.db"
# Country outlines drawn as the map background (built by tools/build_map.py).
# Morocco is drawn with its Sahara territory, as on Moroccan official maps.
MAP_FILE = Path(__file__).resolve().parent / "africa_map.geojson"

# ---------------------------------------------------------------------------
# Colours (all chosen for the dark background)
# ---------------------------------------------------------------------------
INK = "#e6edf3"          # main text
INK_2 = "#aab4c0"        # secondary text
MUTED = "#7d8794"        # axis labels, captions
GRID = "#1c2638"         # chart gridlines
PANEL = "#111a2b"        # panel background
LINE = "#1f2b40"         # panel borders
ACCENT = "#3987e5"       # single-series charts

# Each region keeps the same colour everywhere (colour-blind-safe palette,
# dark-mode steps, fixed order), so filtering never repaints the survivors.
REGION_COLOURS = {
    "Sahel": "#3987e5",
    "Lake Chad Basin": "#d95926",
    "Horn of Africa": "#199e70",
    "Mozambique & Southern Africa": "#c98500",
    "North Africa": "#d55181",
    "Central Africa & Great Lakes": "#008300",
    "Coastal West Africa": "#9085e9",
    "Other": "#e66767",
}

# Severity = an alert level, so it uses the reserved alert colours (low levels
# stay neutral grey) and always comes with a text label, never colour alone.
SEVERITY = {
    1: {"label": "Low", "colour": "#8a96a6", "text": "#0b1220"},
    2: {"label": "Guarded", "colour": "#c3cbd5", "text": "#0b1220"},
    3: {"label": "Elevated", "colour": "#fab219", "text": "#0b1220"},
    4: {"label": "High", "colour": "#ec835a", "text": "#0b1220"},
    5: {"label": "Critical", "colour": "#d03b3b", "text": "#ffffff"},
}
# Heat-map intensity: one hue, dark -> bright.
HEAT_RAMP = ["#104281", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef", "#cde2fb"]

EVENT_TYPES = ["attack", "kidnapping", "military operation", "arrest", "threat", "other"]


def hex_rgb(colour, alpha=255):
    return [int(colour[i:i + 2], 16) for i in (1, 3, 5)] + [alpha]


# ---------------------------------------------------------------------------
# Page style
# ---------------------------------------------------------------------------
CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500&display=swap');
html, body, [class*="css"], .stMarkdown, .stText {{ font-family: 'Inter', system-ui, sans-serif; }}
.stApp {{ background: radial-gradient(1200px 600px at 20% -10%, #13213a 0%, #0b1220 55%) fixed; }}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1500px; }}
section[data-testid="stSidebar"] {{ background: #0d1524; border-right: 1px solid {LINE}; }}
section[data-testid="stSidebar"] .stMarkdown h3 {{ font-size: 0.75rem; letter-spacing: .14em;
    color: {MUTED}; text-transform: uppercase; margin: 0.6rem 0 0.2rem; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ background: {PANEL}; border-color: {LINE} !important;
    border-radius: 12px; }}

/* Top bar */
.topbar {{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;
    padding: 14px 20px; border:1px solid {LINE}; border-radius:12px;
    background: linear-gradient(90deg, #111c30, #0f1829); margin-bottom: 16px; }}
.brand {{ display:flex; align-items:center; gap:12px; font-weight:700; letter-spacing:.12em;
    font-size: 1.05rem; color:{INK}; }}
.brand .mark {{ width:30px; height:30px; border-radius:8px; display:grid; place-items:center;
    background: linear-gradient(135deg, #2a78d6, #104281); font-size: 15px; }}
.tag {{ font-family:'JetBrains Mono', monospace; font-size:.68rem; letter-spacing:.12em; color:{INK_2};
    border:1px solid {LINE}; padding:3px 8px; border-radius:6px; }}
.status {{ font-family:'JetBrains Mono', monospace; font-size:.75rem; color:{INK_2}; letter-spacing:.06em; }}
.pulse {{ display:inline-block; width:8px; height:8px; border-radius:50%; background:#0ca30c;
    margin-right:8px; box-shadow:0 0 0 0 rgba(12,163,12,.6); animation:pulse 2s infinite; }}
@keyframes pulse {{ 0% {{ box-shadow:0 0 0 0 rgba(12,163,12,.55); }}
    70% {{ box-shadow:0 0 0 9px rgba(12,163,12,0); }} 100% {{ box-shadow:0 0 0 0 rgba(12,163,12,0); }} }}

/* Indicator tiles */
.kpis {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap:12px; margin-bottom:16px; }}
.kpi {{ background:{PANEL}; border:1px solid {LINE}; border-radius:12px; padding:14px 16px; }}
.kpi-label {{ font-size:.7rem; letter-spacing:.14em; text-transform:uppercase; color:{MUTED}; }}
.kpi-value {{ font-size:1.9rem; font-weight:700; color:{INK}; margin-top:4px; line-height:1.1; }}
.kpi-sub {{ font-size:.75rem; color:{INK_2}; margin-top:6px; }}

/* Section titles */
.section {{ font-size:.72rem; letter-spacing:.16em; text-transform:uppercase; color:{MUTED};
    margin: 2px 0 8px; font-weight:600; }}

/* Flash reports */
.feed {{ max-height: 488px; overflow-y:auto; padding-right:4px; }}
.flash {{ border:1px solid {LINE}; border-left-width:4px; border-radius:10px; padding:10px 12px;
    margin-bottom:10px; background:#0e1727; }}
.flash-top {{ display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:6px; }}
.badge {{ font-family:'JetBrains Mono', monospace; font-size:.66rem; font-weight:500; letter-spacing:.06em;
    padding:2px 7px; border-radius:5px; white-space:nowrap; }}
.flash-time {{ font-size:.7rem; color:{MUTED}; white-space:nowrap; }}
.flash-title {{ color:{INK}; font-size:.86rem; font-weight:600; line-height:1.3; }}
.flash-meta {{ color:{INK_2}; font-size:.74rem; margin-top:5px; }}
.flash a {{ color:#86b6ef; font-size:.74rem; text-decoration:none; }}

/* Map: sea colour behind our own country shapes */
div[data-testid="stDeckGlJsonChart"] {{ background: #0a1220; border-radius: 10px; overflow: hidden; }}

/* Map legend */
.legend {{ display:flex; flex-wrap:wrap; gap:14px; font-size:.74rem; color:{INK_2}; margin-top:8px; }}
.legend i {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px;
    vertical-align:-1px; }}
</style>
"""


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600)
def load_events(file_changed_at):
    """
    Read all original (non-duplicate) events. `file_changed_at` makes the
    cache refresh as soon as the database file changes.
    """
    # mode=ro opens the database read-only: the dashboard can never change it.
    connection = sqlite3.connect(f"file:{DB_FILE.as_posix()}?mode=ro", uri=True)
    events = pd.read_sql_query(
        """
        SELECT events.*, articles.title,
               (SELECT COUNT(*) FROM events AS d WHERE d.duplicate_of = events.id) AS other_reports
        FROM events JOIN articles ON articles.id = events.article_id
        WHERE events.duplicate_of IS NULL
        """, connection)
    connection.close()

    events["event_date"] = pd.to_datetime(events["event_date"])
    events["region"] = events["region"].fillna("Other")
    events["group_names"] = events["group_names"].fillna("")
    events["place"] = events.apply(
        lambda e: f"{e['city']}, {e['country']}" if pd.notna(e["city"]) else e["country"], axis=1)
    # Whole numbers that may be empty (empty cells show blank, not "None").
    for column in ("killed", "injured", "kidnapped"):
        events[column] = pd.to_numeric(events[column]).astype("Int64")
    return events


@st.cache_data
def load_map():
    """Country shapes + label positions for the map background."""
    shapes = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    for feature in shapes["features"]:
        # African countries a little lighter than their neighbours.
        feature["properties"]["fill"] = [24, 35, 56] if feature["properties"]["africa"] else [17, 26, 42]
    # The map's text layer only draws plain letters, so "Côte" becomes "COTE".
    labels = [{"name": unicodedata.normalize("NFKD", f["properties"]["name"].upper())
                       .encode("ascii", "ignore").decode(),
               "position": [f["properties"]["label_x"], f["properties"]["label_y"]]}
              for f in shapes["features"] if f["properties"]["africa"]]
    return shapes, labels


def base_layers():
    """Our own map background: land, borders and country names."""
    shapes, labels = load_map()
    return [
        pdk.Layer("GeoJsonLayer", data=shapes, stroked=True, filled=True,
                  get_fill_color="properties.fill",
                  get_line_color=[70, 88, 118], line_width_min_pixels=0.8, pickable=False),
        pdk.Layer("TextLayer", data=labels, get_position="position", get_text="name",
                  get_size=10, get_color=[140, 150, 165, 210], font_weight=600,
                  pickable=False),
    ]


def spread_country_points(events):
    """
    Events located only by country all sit on the country's centre and would
    hide each other on the map. Nudge each one a little (always the same way
    for the same event) so they can all be seen.
    """
    events = events.copy()
    country_only = events["location_precision"] == "country"
    dx = (events["id"] * 2654435761 % 1000) / 1000 - 0.5        # -0.5 .. 0.5
    dy = (events["id"] * 40503 % 1000) / 1000 - 0.5
    events.loc[country_only, "latitude"] += dx[country_only] * 1.6
    events.loc[country_only, "longitude"] += dy[country_only] * 1.6
    return events


def days_ago(day):
    n = (date.today() - day.date()).days
    return "Today" if n <= 0 else ("Yesterday" if n == 1 else f"{n} days ago")


# ---------------------------------------------------------------------------
# Filters (left side panel)
# ---------------------------------------------------------------------------
def filters(events):
    """Return (events in the period, events in the previous period, start, end)."""
    sb = st.sidebar
    sb.markdown("### Time window")
    today = date.today()
    period = sb.selectbox("Period", ["Last 7 days", "Last 30 days", "Last 90 days", "All time",
                                     "Custom"], index=1, label_visibility="collapsed")
    if period == "Custom":
        chosen = sb.date_input("From / to", (today - timedelta(days=30), today))
        # While you're still picking, only the first date is set.
        start, end = chosen if len(chosen) == 2 else (chosen[0], chosen[0])
    elif period == "All time":
        start, end = events["event_date"].min().date(), today
    else:
        start, end = today - timedelta(days=int(period.split()[1])), today

    sb.markdown("### Area")
    regions = sb.multiselect("Region", [r for r in REGION_COLOURS if r in set(events["region"])],
                             placeholder="All regions")
    countries = sb.multiselect("Country", sorted(events["country"].dropna().unique()),
                               placeholder="All countries")

    sb.markdown("### Activity")
    types = sb.multiselect("Event type", [t for t in EVENT_TYPES if t in set(events["event_type"])],
                           placeholder="All types")
    all_groups = sorted({g for names in events["group_names"] for g in names.split("; ") if g})
    groups = sb.multiselect("Group", all_groups, placeholder="All groups")
    min_severity = sb.select_slider(
        "Minimum severity", options=[1, 2, 3, 4, 5], value=1,
        format_func=lambda s: f"{s} · {SEVERITY[s]['label']}")

    sb.markdown("### Search")
    search = sb.text_input("Search", placeholder="e.g. Borno, JNIM, otages",
                           label_visibility="collapsed")

    keep = events["severity"] >= min_severity
    if regions:
        keep &= events["region"].isin(regions)
    if countries:
        keep &= events["country"].isin(countries)
    if types:
        keep &= events["event_type"].isin(types)
    if groups:
        keep &= events["group_names"].apply(lambda names: any(g in names.split("; ") for g in groups))
    if search:
        text = events["title"] + " " + events["summary"].fillna("") + " " + events["group_names"]
        keep &= text.str.contains(search, case=False, regex=False)
    matching = events[keep]

    day = matching["event_date"].dt.date
    current = matching[(day >= start) & (day <= end)]
    length = (end - start).days + 1
    previous = matching[(day >= start - timedelta(days=length)) & (day < start)]
    return current, (previous if period != "All time" else None), start, end


# ---------------------------------------------------------------------------
# Page sections
# ---------------------------------------------------------------------------
def top_bar(events):
    last = pd.to_datetime(events["created_at"]).max()
    st.markdown(f"""
<div class="topbar">
  <div class="brand"><div class="mark">◆</div>AFRICA SECURITY MONITOR
    <span class="tag">OSINT · OPEN SOURCES</span></div>
  <div class="status"><span class="pulse"></span>FEED ACTIVE · LAST UPDATE {last:%d %b %Y %H:%M} UTC</div>
</div>""", unsafe_allow_html=True)


def change(now, before):
    """'▲ 40% vs previous period' - neutral wording, no good/bad colour."""
    if before is None:
        return "All recorded events"
    if before == 0:
        return "No events in previous period" if now == 0 else "New vs previous period"
    pct = round((now - before) / before * 100)
    arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "■")
    return f"{arrow} {abs(pct)}% vs previous period"


def indicator_tiles(events, previous):
    def count(df, fn):
        return None if df is None else fn(df)

    tiles = [
        ("Events", len(events), count(previous, len)),
        ("High / critical", int((events["severity"] >= 4).sum()),
         count(previous, lambda d: int((d["severity"] >= 4).sum()))),
        ("Reported killed", int(events["killed"].fillna(0).sum()),
         count(previous, lambda d: int(d["killed"].fillna(0).sum()))),
        ("Reported kidnapped", int(events["kidnapped"].fillna(0).sum()),
         count(previous, lambda d: int(d["kidnapped"].fillna(0).sum()))),
        ("Countries affected", events["country"].nunique(),
         count(previous, lambda d: d["country"].nunique())),
    ]
    html = "".join(
        f'<div class="kpi"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value:,}</div>'
        f'<div class="kpi-sub">{change(value, before)}</div></div>'
        for label, value, before in tiles)
    st.markdown(f'<div class="kpis">{html}</div>', unsafe_allow_html=True)


def threat_map(events):
    st.markdown('<div class="section">Operational map</div>', unsafe_allow_html=True)
    mode = st.segmented_control("Map mode", ["Events", "Heat"], default="Events",
                                label_visibility="collapsed")
    points = spread_country_points(events)
    points["killed"] = points["killed"].astype("float")      # map data must be plain numbers
    points["core"] = points["severity"].map(lambda s: hex_rgb(SEVERITY[s]["colour"], 235))
    points["glow"] = points["severity"].map(lambda s: hex_rgb(SEVERITY[s]["colour"], 55))
    points["radius"] = points["severity"] * 9000 + 6000              # metres
    points["sev_text"] = points["severity"].map(lambda s: f"{s} · {SEVERITY[s]['label']}")
    points["date_text"] = points["event_date"].dt.strftime("%d %b %Y")
    points["killed_text"] = points["killed"].apply(lambda k: f" · {int(k)} killed" if pd.notna(k) else "")
    data = points[["longitude", "latitude", "core", "glow", "radius", "severity", "title",
                   "place", "event_type", "sev_text", "date_text", "killed_text", "group_names"]]

    if mode == "Heat":
        layers = [pdk.Layer("HeatmapLayer", data=data, get_position=["longitude", "latitude"],
                            get_weight="severity", radius_pixels=55, intensity=1.2, threshold=0.05,
                            color_range=[hex_rgb(c)[:3] for c in HEAT_RAMP])]
        tooltip = None
    else:
        layers = [
            # Soft halo behind each point...
            pdk.Layer("ScatterplotLayer", data=data, get_position=["longitude", "latitude"],
                      get_fill_color="glow", get_radius="radius * 2.4", radius_min_pixels=9,
                      radius_max_pixels=40, pickable=False),
            # ...and the point itself, with a thin dark ring so overlaps stay distinct.
            pdk.Layer("ScatterplotLayer", data=data, get_position=["longitude", "latitude"],
                      get_fill_color="core", get_radius="radius", radius_min_pixels=4,
                      radius_max_pixels=16, stroked=True, get_line_color=[11, 18, 32],
                      line_width_min_pixels=1.5, pickable=True),
        ]
        tooltip = {
            "html": "<b>{title}</b><br/>{place} · {date_text}<br/>"
                    "Severity {sev_text} · {event_type}{killed_text}<br/>{group_names}",
            "style": {"backgroundColor": "#0e1727", "color": INK, "fontSize": "12.5px",
                      "border": f"1px solid {LINE}", "borderRadius": "8px", "maxWidth": "320px"},
        }

    deck = pdk.Deck(
        layers=base_layers() + layers,
        # Centred so the whole continent fits, from Tangier to Cape Town.
        initial_view_state=pdk.ViewState(latitude=7, longitude=15, zoom=2.25),
        # Mouse wheel scrolls the page, not the map (use +/- or double-click to zoom).
        views=[pdk.View(type="MapView", controller={"scrollZoom": False, "doubleClickZoom": True})],
        # No map tiles: the countries are drawn by base_layers() above.
        map_provider=None,
        map_style=None,
        tooltip=tooltip,
    )
    st.pydeck_chart(deck, use_container_width=True, height=440)

    if mode == "Heat":
        st.markdown('<div class="legend">Brighter = more, and more severe, events in the area. '
                    'Switch to <b>&nbsp;Events&nbsp;</b> to see individual reports.</div>',
                    unsafe_allow_html=True)
    else:
        chips = "".join(f'<span><i style="background:{v["colour"]}"></i>{s} · {v["label"]}</span>'
                        for s, v in SEVERITY.items())
        st.markdown(f'<div class="legend">{chips}<span style="color:{MUTED}">Bigger = more severe · '
                    'country-level reports are spread around the country centre</span></div>',
                    unsafe_allow_html=True)


def flash_reports(events):
    st.markdown('<div class="section">Flash reports</div>', unsafe_allow_html=True)
    serious = events[events["severity"] >= 3]
    latest = (serious if len(serious) >= 3 else events).sort_values(
        ["event_date", "severity"], ascending=[False, False]).head(12)
    cards = []
    for _, e in latest.iterrows():
        sev = SEVERITY[int(e["severity"])]
        meta = [escape(e["place"]), escape(e["event_type"])]
        if pd.notna(e["killed"]):
            meta.append(f"{e['killed']} killed")
        if e["group_names"]:
            meta.append(escape(e["group_names"]))
        extra = f" (+{e['other_reports']})" if e["other_reports"] else ""
        cards.append(
            f'<div class="flash" style="border-left-color:{sev["colour"]}">'
            f'<div class="flash-top"><span class="badge" style="background:{sev["colour"]};'
            f'color:{sev["text"]}">SEV {int(e["severity"])} · {sev["label"].upper()}</span>'
            f'<span class="flash-time">{days_ago(e["event_date"])}</span></div>'
            f'<div class="flash-title">{escape(e["title"])}</div>'
            f'<div class="flash-meta">📍 {" · ".join(meta)}</div>'
            f'<a href="{escape(e["url"], quote=True)}" target="_blank">{escape(e["source"])}{extra} ↗</a>'
            f'</div>')
    st.markdown(f'<div class="feed">{"".join(cards)}</div>', unsafe_allow_html=True)


def dark_chart(chart, height):
    """Shared look for every chart: transparent background, quiet axes."""
    return (chart.properties(height=height, background="transparent")
            .configure_view(stroke=None)
            .configure_axis(labelColor=MUTED, titleColor=MUTED, gridColor=GRID, domainColor=LINE,
                            tickColor=LINE, labelFontSize=11, titleFontSize=11,
                            titleFontWeight="normal")
            .configure_legend(labelColor=INK_2, titleColor=MUTED, labelFontSize=11,
                              titleFontSize=11, labelLimit=260, symbolType="circle")
            .configure_title(color=INK, fontSize=13, anchor="start", fontWeight=600))


def activity_timeline(events, start, end):
    period_name, freq = ("Week", "W") if (end - start).days > 21 else ("Day", "D")
    counts = (events.assign(period=events["event_date"].dt.to_period(freq).dt.start_time)
                    .groupby(["period", "region"]).size().reset_index(name="events"))
    # Every day/week of the period gets a slot, so quiet ones show as gaps.
    label = "%d %b" if freq == "D" else "w/c %d %b"
    all_periods = pd.period_range(start, end, freq=freq).start_time
    counts["label"] = counts["period"].dt.strftime(label)
    present = [r for r in REGION_COLOURS if r in set(counts["region"])]
    chart = (
        alt.Chart(counts, title=f"Activity per {period_name.lower()}, by region")
        .mark_bar(stroke=PANEL, strokeWidth=2)            # 2px gap between stacked segments
        .encode(
            x=alt.X("label:O", title=None,
                    scale=alt.Scale(domain=list(all_periods.strftime(label)), paddingInner=0.3),
                    axis=alt.Axis(labelAngle=0, labelOverlap=True)),
            y=alt.Y("events:Q", title="Events", axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("region:N", title=None,
                            scale=alt.Scale(domain=present, range=[REGION_COLOURS[r] for r in present]),
                            legend=alt.Legend(orient="bottom", columns=3)),
            order=alt.Order("region:N"),
            tooltip=[alt.Tooltip("period:T", title=f"{period_name} starting", format="%d %b %Y"),
                     alt.Tooltip("region:N", title="Region"),
                     alt.Tooltip("events:Q", title="Events")],
        )
    )
    st.altair_chart(dark_chart(chart, 300), use_container_width=True, theme=None)


def ranking(events, column, title, top=8, explode=False, height=230):
    """Horizontal bars: one series, one colour, no legend needed."""
    values = events[column]
    if explode:
        values = values.str.split("; ").explode()
        values = values[values != ""]
    counts = values.value_counts().head(top).reset_index()
    counts.columns = ["name", "events"]
    if counts.empty:
        st.caption(f"{title}: nothing to show for these filters.")
        return
    chart = (
        alt.Chart(counts, title=title)
        .mark_bar(color=ACCENT, cornerRadiusEnd=4, height=13)
        .encode(
            x=alt.X("events:Q", title=None, axis=alt.Axis(tickMinStep=1)),
            y=alt.Y("name:N", sort="-x", title=None, axis=alt.Axis(labelColor=INK_2, labelLimit=190)),
            tooltip=[alt.Tooltip("name:N", title=title.split(" ")[-1].capitalize()),
                     alt.Tooltip("events:Q", title="Events")],
        )
    )
    # Same height for every ranking, so panels side by side line up.
    st.altair_chart(dark_chart(chart, height), use_container_width=True, theme=None)


def event_log(events):
    st.markdown(f'<div class="section">Event log · {len(events):,} records</div>',
                unsafe_allow_html=True)
    table = events.sort_values(["event_date", "severity"], ascending=[False, False]).copy()
    table["level"] = table["severity"].map(lambda s: f"{s} · {SEVERITY[s]['label']}")
    table = table[["event_date", "level", "event_type", "place", "region", "group_names",
                   "killed", "kidnapped", "title", "source", "other_reports", "url"]]
    st.dataframe(
        table, hide_index=True, use_container_width=True, height=420,
        column_config={
            "event_date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
            "level": st.column_config.TextColumn("Severity", help="1 (low) to 5 (critical)"),
            "event_type": "Type",
            "place": "Place",
            "region": "Region",
            "group_names": "Group",
            "killed": st.column_config.NumberColumn("Killed"),
            "kidnapped": st.column_config.NumberColumn("Kidnapped"),
            "title": st.column_config.TextColumn("Headline", width="large"),
            "source": "Source",
            "other_reports": st.column_config.NumberColumn("Other sources"),
            "url": st.column_config.LinkColumn("Link", display_text="Open ↗"),
        },
    )
    st.download_button("⬇  Export these events (CSV)", table.to_csv(index=False).encode("utf-8"),
                       file_name="africa_security_events.csv", mime="text/csv")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Africa Security Monitor", page_icon="◆", layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)

    if not DB_FILE.exists():
        st.error(f"Database not found: {DB_FILE}. Run the pipeline first.")
        return
    events = load_events(DB_FILE.stat().st_mtime)
    if events.empty:
        st.info("No events in the database yet.")
        return

    top_bar(events)
    current, previous, start, end = filters(events)
    st.sidebar.caption("Open-source news, classified automatically. Read-only view of "
                       "data/monitor.db.")
    if current.empty:
        st.info("No events match these filters. Try a longer period or fewer filters.")
        return

    indicator_tiles(current, previous)

    left, right = st.columns([2.3, 1], gap="medium")
    with left:
        with st.container(border=True):
            threat_map(current)
    with right:
        with st.container(border=True):
            flash_reports(current)

    left, right = st.columns([1.6, 1], gap="medium")
    with left:
        with st.container(border=True):
            activity_timeline(current, start, end)
    with right:
        with st.container(border=True):
            ranking(current, "region", "Most affected regions", height=332)

    left, right = st.columns(2, gap="medium")
    with left:
        with st.container(border=True):
            ranking(current, "event_type", "Event types")
    with right:
        with st.container(border=True):
            ranking(current, "group_names", "Most active groups", explode=True)

    with st.container(border=True):
        event_log(current)


main()
