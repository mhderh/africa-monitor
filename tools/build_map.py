"""
Builds dashboard/africa_map.geojson - the country outlines drawn on the
dashboard map - from Natural Earth's public-domain country file.

Morocco is drawn as on Moroccan official maps: Morocco and its Sahara
territory are merged into one country, with no internal border.

You only need this if you want to rebuild the map file. One-time setup:

    python -m venv .mapenv
    .mapenv\\Scripts\\pip install shapely
    (download ne_50m_admin_0_countries.geojson from
     https://github.com/nvkelso/natural-earth-vector/tree/master/geojson)

Then:

    .mapenv\\Scripts\\python tools\\build_map.py path\\to\\ne_50m_admin_0_countries.geojson
"""

import json
import sys
from pathlib import Path

from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

OUT = Path(__file__).resolve().parent.parent / "dashboard" / "africa_map.geojson"

# Area kept: Africa plus the edges of Europe and the Middle East for context.
AREA = box(-26, -38, 62, 46)
SIMPLIFY = 0.03          # degrees; smaller = more detail, bigger file
MERGE_INTO_MOROCCO = {"MAR", "SAH"}


def rounded(geometry, digits=3):
    """Round coordinates to keep the file small (3 decimals = about 100 m)."""
    def walk(coords):
        if isinstance(coords[0], (int, float)):
            return [round(c, digits) for c in coords]
        return [walk(c) for c in coords]
    geo = mapping(geometry)
    return {"type": geo["type"], "coordinates": walk(geo["coordinates"])}


def main(source):
    data = json.loads(Path(source).read_text(encoding="utf-8"))
    countries, morocco_parts, morocco_props = [], [], None

    for feature in data["features"]:
        props = feature["properties"]
        geometry = shape(feature["geometry"])
        if not geometry.intersects(AREA):
            continue
        if props["ADM0_A3"] in MERGE_INTO_MOROCCO:
            morocco_parts.append(geometry)
            if props["ADM0_A3"] == "MAR":
                morocco_props = props
            continue
        countries.append((props, geometry))

    # One Morocco, from Tangier to Lagouira, without the internal line.
    countries.append((morocco_props, unary_union(morocco_parts).buffer(0)))

    features = []
    for props, geometry in countries:
        geometry = geometry.intersection(AREA).simplify(SIMPLIFY, preserve_topology=True)
        if geometry.is_empty:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "name": props["NAME"],
                "africa": props["CONTINENT"] == "Africa",
                "label_x": round(props["LABEL_X"], 2),
                "label_y": round(props["LABEL_Y"], 2),
            },
            "geometry": rounded(geometry),
        })

    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                              separators=(",", ":")), encoding="utf-8")
    print(f"{len(features)} countries -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
