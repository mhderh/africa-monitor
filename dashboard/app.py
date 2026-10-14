"""
Web dashboard for the Africa security monitor (Streamlit).

Run it on your computer from the project folder:

    streamlit run dashboard/app.py

It opens in your browser at http://localhost:8501. It READS the official
database (data/monitor.db) and never changes it. Run `git pull` first to get
the latest data from GitHub.
"""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

DB_FILE = Path(__file__).resolve().parent.parent / "data" / "monitor.db"

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
# Each region always keeps the same colour (a colour-blind-safe palette, used
# in this fixed order), so filtering never repaints the survivors.
REGION_COLOURS = {
    "Sahel": "#2a78d6",
    "Lake Chad Basin": "#eb6834",
    "Horn of Africa": "#1baf7a",
    "Mozambique & Southern Africa": "#eda100",
    "North Africa": "#e87ba4",
    "Central Africa & Great Lakes": "#008300",
    "Coastal West Africa": "#4a3aa7",
    "Other": "#e34948",
}
# Severity 1 -> 5 = one hue, light -> dark (dot size grows with it too).
SEVERITY_COLOURS = {1: "#86b6ef", 2: "#5598e7", 3: "#2a78d6", 4: "#1c5cab", 5: "#104281"}
MUTED_INK = "#898781"
GRID = "#e1e0d9"

EVENT_TYPES = ["attack", "kidnapping", "military operation", "arrest", "threat", "other"]


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


def spread_country_points(events):
    """
    Events located only by country all sit on the country's centre and would
    hide each other on the map. Nudge each one a little (always the same way
    for the same event) so they can all be seen.
    """
    events = events.copy()
    country_only = events["location_precision"] == "country"
    offsets = (events["id"] * 2654435761 % 1000) / 1000 - 0.5        # -0.5 .. 0.5
    events.loc[country_only, "latitude"] += offsets[country_only] * 1.6
    events.loc[country_only, "longitude"] += ((events["id"] * 40503 % 1000) / 1000 - 0.5)[country_only] * 1.6
    return events


# ---------------------------------------------------------------------------
# Filters (one row above the charts, extra ones in an expander)
# ---------------------------------------------------------------------------
def filter_events(events):
    col_period, col_region, col_severity, col_search = st.columns([1.1, 2, 1.2, 1.7])

    today = date.today()
    with col_period:
        period = st.selectbox("Period", ["Last 7 days", "Last 30 days", "Last 90 days",
                                         "All time", "Custom"], index=1)
        if period == "Custom":
            chosen = st.date_input("From / to", (today - timedelta(days=30), today))
            # While you're still picking, only the first date is set.
            start, end = chosen if len(chosen) == 2 else (chosen[0], chosen[0])
    if period == "All time":
        start, end = events["event_date"].min().date(), today
    elif period != "Custom":
        days = int(period.split()[1])
        start, end = today - timedelta(days=days), today

    with col_region:
        regions = st.multiselect("Region", [r for r in REGION_COLOURS if r in set(events["region"])],
                                 placeholder="All regions")
    with col_severity:
        min_severity = st.select_slider("Minimum severity", options=[1, 2, 3, 4, 5], value=1)
    with col_search:
        search = st.text_input("Search headlines", placeholder="e.g. Borno, JNIM, otages")

    with st.expander("More filters: country, event type, group"):
        c1, c2, c3 = st.columns(3)
        countries = c1.multiselect("Country", sorted(events["country"].dropna().unique()),
                                   placeholder="All countries")
        types = c2.multiselect("Event type", [t for t in EVENT_TYPES if t in set(events["event_type"])],
                               placeholder="All types")
        all_groups = sorted({g for names in events["group_names"] for g in names.split("; ") if g})
        groups = c3.multiselect("Group", all_groups, placeholder="All groups")

    keep = (events["event_date"].dt.date >= start) & (events["event_date"].dt.date <= end)
    keep &= events["severity"] >= min_severity
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
    return events[keep], start, end


# ---------------------------------------------------------------------------
# Page sections
# ---------------------------------------------------------------------------
def show_headline_numbers(events):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Events", f"{len(events):,}")
    c2.metric("High severity (4–5)", f"{(events['severity'] >= 4).sum():,}")
    c3.metric("Reported killed", f"{int(events['killed'].fillna(0).sum()):,}")
    c4.metric("Reported kidnapped", f"{int(events['kidnapped'].fillna(0).sum()):,}")


def show_map(events):
    st.subheader("Map")
    points = spread_country_points(events)
    points["colour"] = points["severity"].map(
        lambda s: [int(SEVERITY_COLOURS[s][i:i + 2], 16) for i in (1, 3, 5)])
    points["radius"] = points["severity"] * 12000 + 8000      # metres
    points["killed_text"] = points["killed"].apply(lambda k: f"{k} killed ·" if pd.notna(k) else "")
    points["killed"] = points["killed"].astype("float")      # map data must be plain numbers
    points["date_text"] = points["event_date"].dt.strftime("%d %b %Y")

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=points[["longitude", "latitude", "colour", "radius", "title", "place",
                     "event_type", "severity", "date_text", "killed_text", "group_names"]],
        get_position=["longitude", "latitude"],
        get_fill_color="colour",
        get_radius="radius",
        radius_min_pixels=5,           # stays visible when zoomed out
        radius_max_pixels=22,
        stroked=True,
        get_line_color=[252, 252, 251],   # thin light ring so overlapping dots stay distinct
        line_width_min_pixels=1.5,
        pickable=True,
        opacity=0.9,
    )
    tooltip = {
        "html": "<b>{title}</b><br/>{place} · {date_text}<br/>"
                "Severity {severity} · {event_type}<br/>{killed_text} {group_names}",
        "style": {"fontSize": "13px", "maxWidth": "320px"},
    }
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=5, longitude=17, zoom=2.7),
        # Mouse wheel scrolls the page, not the map (use the +/- buttons or
        # double-click to zoom; drag to move).
        views=[pdk.View(type="MapView", controller={"scrollZoom": False, "doubleClickZoom": True})],
        map_provider="carto",
        map_style="light",             # light basemap, free, no account needed
        tooltip=tooltip,
    )
    st.pydeck_chart(deck, use_container_width=True, height=520)

    legend = " &nbsp; ".join(
        f"<span style='color:{colour};font-size:{10 + 2 * s}px'>●</span> {s}"
        for s, colour in SEVERITY_COLOURS.items())
    st.caption(f"Severity (darker and bigger = more severe): {legend}. "
               "Events located only by country are spread slightly around its centre.",
               unsafe_allow_html=True)


def show_trends(events, start, end):
    st.subheader("Trends")
    left, right = st.columns([3, 2])

    # Events per week, stacked by region.
    # Count per week for long periods, per day for short ones.
    period_name, freq = ("Week", "W") if (end - start).days > 21 else ("Day", "D")
    counts = (events.assign(period=events["event_date"].dt.to_period(freq).dt.start_time)
                    .groupby(["period", "region"]).size().reset_index(name="events"))
    # Every day/week of the chosen period gets a slot, so quiet weeks show
    # as gaps instead of disappearing.
    all_periods = pd.period_range(start, end, freq=freq).start_time
    label = "%d %b" if freq == "D" else "w/c %d %b"          # w/c = week starting
    counts["label"] = counts["period"].dt.strftime(label)
    present = [r for r in REGION_COLOURS if r in set(counts["region"])]
    bars = (
        alt.Chart(counts)
        .mark_bar(stroke="#fcfcfb", strokeWidth=2)        # 2px gap between stacked segments
        .encode(
            x=alt.X("label:O", title=None,
                    scale=alt.Scale(domain=list(all_periods.strftime(label)), paddingInner=0.25),
                    axis=alt.Axis(labelAngle=0, labelColor=MUTED_INK, labelOverlap=True)),
            y=alt.Y("events:Q", title="Events",
                    axis=alt.Axis(gridColor=GRID, labelColor=MUTED_INK, titleColor=MUTED_INK,
                                  tickMinStep=1)),
            color=alt.Color("region:N", title="Region",
                            scale=alt.Scale(domain=present,
                                            range=[REGION_COLOURS[r] for r in present]),
                            legend=alt.Legend(orient="bottom", columns=2, labelLimit=260)),
            order=alt.Order("region:N"),
            tooltip=[alt.Tooltip("period:T", title=period_name + " starting", format="%d %b %Y"),
                     alt.Tooltip("region:N", title="Region"),
                     alt.Tooltip("events:Q", title="Events")],
        )
        .properties(height=320, title=f"Events per {period_name.lower()}, by region")
    )
    left.altair_chart(bars, use_container_width=True)

    # Busiest countries (one series -> one colour, no legend needed).
    top = events.groupby("country").size().nlargest(10).reset_index(name="events")
    countries = (
        alt.Chart(top)
        .mark_bar(color=REGION_COLOURS["Sahel"], cornerRadiusEnd=4, height=14)
        .encode(
            x=alt.X("events:Q", title="Events",
                    axis=alt.Axis(gridColor=GRID, labelColor=MUTED_INK, titleColor=MUTED_INK,
                                  tickMinStep=1)),
            y=alt.Y("country:N", sort="-x", title=None, axis=alt.Axis(labelColor="#52514e")),
            tooltip=[alt.Tooltip("country:N", title="Country"),
                     alt.Tooltip("events:Q", title="Events")],
        )
        .properties(height=320, title="Busiest countries")
    )
    right.altair_chart(countries, use_container_width=True)


def show_table(events):
    st.subheader(f"Events ({len(events):,})")
    table = events.sort_values(["event_date", "severity"], ascending=[False, False])[
        ["event_date", "severity", "event_type", "place", "region", "group_names",
         "killed", "kidnapped", "title", "source", "other_reports", "url"]]
    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "event_date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
            "severity": st.column_config.NumberColumn("Sev.", help="1 (low) to 5 (very high)"),
            "event_type": "Type",
            "place": "Place",
            "region": "Region",
            "group_names": "Group",
            "killed": st.column_config.NumberColumn("Killed"),
            "kidnapped": st.column_config.NumberColumn("Kidnapped"),
            "title": st.column_config.TextColumn("Headline", width="large"),
            "source": "Source",
            "other_reports": st.column_config.NumberColumn("Other sources"),
            "url": st.column_config.LinkColumn("Link", display_text="Open"),
        },
    )
    st.download_button("Download these events (CSV)", table.to_csv(index=False).encode("utf-8"),
                       file_name="africa_security_events.csv", mime="text/csv")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Africa Security Monitor", page_icon="🌍", layout="wide")
    st.title("Africa Security Monitor")

    if not DB_FILE.exists():
        st.error(f"Database not found: {DB_FILE}. Run the pipeline first.")
        return
    events = load_events(DB_FILE.stat().st_mtime)
    if events.empty:
        st.info("No events in the database yet.")
        return

    last_update = pd.to_datetime(events["created_at"]).max()
    st.caption(f"Open-source news, classified automatically (rule-based). "
               f"Last update: {last_update:%d %b %Y %H:%M} UTC.")

    filtered, start, end = filter_events(events)
    if filtered.empty:
        st.info("No events match these filters. Try a longer period or fewer filters.")
        return

    show_headline_numbers(filtered)
    show_map(filtered)
    show_trends(filtered, start, end)
    show_table(filtered)


main()
