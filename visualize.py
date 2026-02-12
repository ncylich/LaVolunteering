"""Generate an interactive choropleth Leaflet map of volunteer opportunities by zip code."""

import csv
import json
import os
import re
import urllib.request

from config import OUTPUT_DIR

CSV_PATH = os.path.join(OUTPUT_DIR, "opportunities.csv")
HTML_PATH = os.path.join(OUTPUT_DIR, "map.html")
BOUNDARIES_CACHE = os.path.join(OUTPUT_DIR, "ca_zipcodes.geojson")

# CA zip code boundaries (Census ZCTA data via OpenDataDE)
BOUNDARIES_URL = (
    "https://raw.githubusercontent.com/OpenDataDE/State-zip-code-GeoJSON/"
    "master/ca_california_zip_codes_geo.min.json"
)

ZIP_RE = re.compile(r"\b(\d{5})\b")

LA_CENTER = (34.05, -118.25)
LA_ZOOM = 10


def extract_zipcode(location: str) -> str | None:
    """Pull a 5-digit zip code from a location string like 'Los Angeles, CA 90065'."""
    m = ZIP_RE.search(location or "")
    return m.group(1) if m else None


def group_by_zip(csv_path: str) -> tuple[dict[str, list[dict]], list[dict]]:
    """Read CSV and return ({zipcode: [opportunities]}, [virtual_opportunities])."""
    by_zip: dict[str, list[dict]] = {}
    virtual: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            zc = extract_zipcode(row.get("location", ""))
            if zc:
                by_zip.setdefault(zc, []).append(row)
            else:
                virtual.append(row)
    return by_zip, virtual


def download_boundaries() -> dict:
    """Download and cache CA zip code boundary GeoJSON."""
    if os.path.exists(BOUNDARIES_CACHE):
        print(f"Loading cached boundaries from {BOUNDARIES_CACHE}")
        with open(BOUNDARIES_CACHE, encoding="utf-8") as f:
            return json.load(f)

    print("Downloading CA zip code boundaries...")
    req = urllib.request.Request(
        BOUNDARIES_URL, headers={"User-Agent": "volunteer-scraper/1.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    os.makedirs(os.path.dirname(BOUNDARIES_CACHE) or ".", exist_ok=True)
    with open(BOUNDARIES_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"Cached {len(data.get('features', []))} boundary features to {BOUNDARIES_CACHE}")
    return data


def _find_zip_property(feature: dict) -> str | None:
    """Auto-detect the property name containing the zip code."""
    props = feature.get("properties", {})
    for key in ["ZCTA5CE10", "ZCTA5CE20", "ZIP", "ZIPCODE", "zip", "GEOID10", "GEOID20"]:
        val = props.get(key, "")
        if isinstance(val, str) and ZIP_RE.fullmatch(val):
            return key
    for key, val in props.items():
        if isinstance(val, str) and ZIP_RE.fullmatch(val):
            return key
    return None


def build_choropleth_geojson(
    by_zip: dict[str, list[dict]], boundaries: dict
) -> dict:
    """Merge opportunity data with zip code boundary polygons."""
    zip_key = None
    for feat in boundaries["features"][:5]:
        zip_key = _find_zip_property(feat)
        if zip_key:
            break
    if not zip_key:
        sample = list(boundaries["features"][0]["properties"].keys()) if boundaries["features"] else []
        raise ValueError(f"Cannot find zip code property. Available: {sample}")

    features = []
    matched = set()
    for feature in boundaries["features"]:
        zc = str(feature["properties"].get(zip_key, ""))
        if zc in by_zip:
            opps = by_zip[zc]
            features.append(
                {
                    "type": "Feature",
                    "geometry": feature["geometry"],
                    "properties": {
                        "zipcode": zc,
                        "count": len(opps),
                        "opportunities": [
                            {
                                "title": o["title"],
                                "organization": o["organization"],
                                "date": o.get("date", ""),
                                "time": o.get("time", ""),
                                "type": o.get("opportunity_type", ""),
                                "url": o.get("opportunity_url", ""),
                            }
                            for o in opps
                        ],
                    },
                }
            )
            matched.add(zc)

    unmatched = set(by_zip.keys()) - matched
    if unmatched:
        print(f"  Warning: {len(unmatched)} zip codes not found in boundaries: {sorted(unmatched)[:10]}")

    return {"type": "FeatureCollection", "features": features}


HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>LA Volunteer Opportunities Map</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }

/* ── Header ── */
#header {
  height: 52px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 16px;
  z-index: 1001;
  position: relative;
}
#header h1 { font-size: 16px; font-weight: 700; color: #111; white-space: nowrap; }
.stat-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.stat-chip {
  background: #f3f4f6; border-radius: 12px; padding: 4px 12px;
  font-size: 12px; color: #374151; white-space: nowrap;
}
.stat-chip strong { color: #111; }
#sidebar-toggle {
  background: none; border: 1px solid #d1d5db; border-radius: 6px;
  padding: 6px 10px; cursor: pointer; font-size: 14px; color: #374151;
  margin-left: auto;
}
#sidebar-toggle:hover { background: #f3f4f6; }

/* ── Layout ── */
#container { display: flex; height: calc(100vh - 52px); }

/* ── Sidebar ── */
#sidebar {
  width: 340px; min-width: 340px; background: #fff;
  border-right: 1px solid #e5e7eb; display: flex; flex-direction: column;
  overflow: hidden; transition: margin-left 0.3s ease;
}
#sidebar.collapsed { margin-left: -340px; }

.filter-section {
  padding: 12px 16px; border-bottom: 1px solid #e5e7eb;
}
.filter-section h3 {
  font-size: 12px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.05em; color: #6b7280; margin-bottom: 10px;
}
.filter-group { margin-bottom: 10px; }
.filter-group label {
  font-size: 13px; color: #374151; display: flex; align-items: center;
  gap: 6px; padding: 3px 0; cursor: pointer;
}
.filter-group label:hover { color: #111; }
.type-dot {
  width: 10px; height: 10px; border-radius: 50%;
  display: inline-block; flex-shrink: 0;
}
.filter-group input[type="text"] {
  width: 100%; padding: 6px 10px; border: 1px solid #d1d5db;
  border-radius: 6px; font-size: 13px; outline: none;
}
.filter-group input[type="text"]:focus {
  border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59,130,246,0.15);
}
.btn-reset {
  background: none; border: 1px solid #d1d5db; border-radius: 6px;
  padding: 4px 12px; font-size: 12px; color: #6b7280; cursor: pointer;
}
.btn-reset:hover { background: #f3f4f6; color: #374151; }

#zip-list-header {
  padding: 10px 16px; font-size: 12px; color: #6b7280;
  font-weight: 600; border-bottom: 1px solid #f3f4f6;
}

#zip-list { flex: 1; overflow-y: auto; }
.zip-item {
  display: flex; align-items: center; padding: 8px 16px; cursor: pointer;
  border-bottom: 1px solid #f9fafb; gap: 10px; transition: background 0.15s;
}
.zip-item:hover { background: #f9fafb; }
.zip-item.active { background: #eff6ff; }
.zip-code { font-weight: 600; font-size: 13px; color: #111; width: 50px; flex-shrink: 0; }
.zip-bar-container {
  flex: 1; height: 8px; background: #f3f4f6; border-radius: 4px; overflow: hidden;
}
.zip-bar { height: 100%; border-radius: 4px; transition: width 0.3s ease; }
.zip-count { font-size: 12px; color: #6b7280; width: 30px; text-align: right; flex-shrink: 0; }

/* ── Virtual section ── */
#virtual-section {
  border-top: 1px solid #e5e7eb; max-height: 200px;
  overflow: hidden; transition: max-height 0.3s ease;
}
#virtual-section.collapsed { max-height: 38px; }
#virtual-header {
  padding: 10px 16px; font-size: 12px; font-weight: 600; color: #6b7280;
  cursor: pointer; display: flex; align-items: center;
  justify-content: space-between; background: #fafafa;
}
#virtual-header:hover { background: #f3f4f6; }
#virtual-header .arrow { transition: transform 0.3s; font-size: 10px; }
#virtual-section.collapsed .arrow { transform: rotate(-90deg); }
#virtual-list { overflow-y: auto; max-height: 160px; }
.virtual-item { padding: 6px 16px; font-size: 12px; border-bottom: 1px solid #f3f4f6; }
.virtual-item a { color: #3b82f6; text-decoration: none; }
.virtual-item a:hover { text-decoration: underline; }
.virtual-item .v-org { color: #9ca3af; font-size: 11px; }

/* ── Map ── */
#map { flex: 1; z-index: 1; }

/* ── Popup overrides ── */
.leaflet-popup-content-wrapper {
  border-radius: 10px !important; padding: 0 !important;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important;
}
.leaflet-popup-content { margin: 0 !important; min-width: 280px; max-width: 350px; }
.leaflet-popup-close-button { color: #9ca3af !important; font-size: 20px !important; padding: 8px 10px !important; }
.popup-content h3 {
  font-size: 14px; font-weight: 700; padding: 12px 16px 8px;
  border-bottom: 1px solid #f3f4f6; color: #111;
}
.popup-list { max-height: 260px; overflow-y: auto; padding: 4px 0; }
.popup-item { padding: 6px 16px; display: flex; gap: 8px; align-items: flex-start; }
.popup-item .type-dot { margin-top: 5px; flex-shrink: 0; }
.popup-item-content { flex: 1; min-width: 0; }
.popup-item a {
  color: #111; text-decoration: none; font-size: 13px; font-weight: 500;
  display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.popup-item a:hover { color: #3b82f6; }
.popup-meta { font-size: 11px; color: #9ca3af; margin-top: 1px; }
.popup-more {
  text-align: center; font-size: 12px; color: #6b7280;
  padding: 6px; border-top: 1px solid #f3f4f6;
}

/* ── Tooltip override ── */
.leaflet-tooltip {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 13px; border-radius: 6px; padding: 4px 10px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.15);
}

/* ── Legend ── */
#legend {
  position: absolute; bottom: 30px; right: 10px; z-index: 1000;
  background: rgba(255,255,255,0.95); padding: 12px 16px; border-radius: 10px;
  font-size: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.15);
  backdrop-filter: blur(4px);
}
#legend h4 {
  margin: 0 0 8px; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.05em; color: #6b7280;
}
.legend-gradient {
  width: 140px; height: 12px; border-radius: 6px;
  background: linear-gradient(to right, #fef0d9, #fdcc8a, #fc8d59, #e34a33, #b30000);
  margin: 4px 0 2px; border: 1px solid rgba(0,0,0,0.1);
}
.legend-gradient-labels { display: flex; justify-content: space-between; font-size: 10px; color: #9ca3af; }

/* ── No results ── */
.no-results { padding: 24px 16px; text-align: center; color: #9ca3af; font-size: 13px; }

@media (max-width: 768px) {
  #sidebar {
    position: absolute; z-index: 1001; height: calc(100vh - 52px);
    box-shadow: 2px 0 8px rgba(0,0,0,0.1);
  }
}
</style>
</head>
<body>

<div id="header">
  <h1>LA Volunteer Opportunities</h1>
  <div class="stat-chips">
    <span class="stat-chip"><strong id="stat-total">__TOTAL_MAPPED__</strong> mapped</span>
    <span class="stat-chip"><strong id="stat-zips">__TOTAL_ZIPS__</strong> zip codes</span>
    <span class="stat-chip"><strong>__VIRTUAL_COUNT__</strong> virtual</span>
  </div>
  <button id="sidebar-toggle" title="Toggle sidebar">&#9776;</button>
</div>

<div id="container">
  <div id="sidebar">
    <div class="filter-section">
      <h3>Filters</h3>
      <div class="filter-group" id="type-filters"></div>
      <div class="filter-group">
        <input type="text" id="org-search" placeholder="Search organization..."/>
      </div>
      <div class="filter-group">
        <label><input type="checkbox" id="upcoming-only"/> Upcoming events only</label>
      </div>
      <div class="filter-actions">
        <button class="btn-reset" id="reset-filters">Reset filters</button>
      </div>
    </div>
    <div id="zip-list-header">Loading...</div>
    <div id="zip-list"></div>
    <div id="virtual-section" class="collapsed">
      <div id="virtual-header">
        <span>Virtual Opportunities (<span id="virtual-count-label">__VIRTUAL_COUNT__</span>)</span>
        <span class="arrow">&#9660;</span>
      </div>
      <div id="virtual-list"></div>
    </div>
  </div>
  <div id="map"></div>
</div>

<div id="legend">
  <h4>Opportunities per Zip Code</h4>
  <div class="legend-gradient"></div>
  <div class="legend-gradient-labels">
    <span>1</span>
    <span id="legend-max">__MAX_COUNT__</span>
  </div>
</div>

<script>
// ── Data ────────────────────────────────────────────────
var allData = __GEOJSON_DATA__;
var virtualOpps = __VIRTUAL_DATA__;

var TYPE_COLORS = {
  'Volunteer Opportunity': '#3b82f6',
  'Special Event': '#10b981',
  'Training': '#f59e0b',
  'Already Filled': '#9ca3af'
};

// ── Helpers ─────────────────────────────────────────────
function escapeHtml(str) {
  var div = document.createElement('div');
  div.textContent = str || '';
  return div.innerHTML;
}

var COLOR_STOPS = [
  [254, 240, 217],
  [253, 204, 138],
  [252, 141, 89],
  [227, 74, 51],
  [179, 0, 0]
];

function getColor(ratio) {
  var r = Math.max(0, Math.min(1, ratio));
  var idx = r * (COLOR_STOPS.length - 1);
  var lo = Math.floor(idx);
  var hi = Math.min(lo + 1, COLOR_STOPS.length - 1);
  var t = idx - lo;
  var R = Math.round(COLOR_STOPS[lo][0] + t * (COLOR_STOPS[hi][0] - COLOR_STOPS[lo][0]));
  var G = Math.round(COLOR_STOPS[lo][1] + t * (COLOR_STOPS[hi][1] - COLOR_STOPS[lo][1]));
  var B = Math.round(COLOR_STOPS[lo][2] + t * (COLOR_STOPS[hi][2] - COLOR_STOPS[lo][2]));
  return 'rgb(' + R + ',' + G + ',' + B + ')';
}

function buildPopupHtml(p) {
  var html = '<div class="popup-content">';
  html += '<h3>' + escapeHtml(p.zipcode) + ' &mdash; ' + p.count
    + ' opportunit' + (p.count === 1 ? 'y' : 'ies') + '</h3>';
  html += '<div class="popup-list">';
  var show = p.opportunities.slice(0, 15);
  show.forEach(function(o) {
    var color = TYPE_COLORS[o.type] || '#9ca3af';
    html += '<div class="popup-item">';
    html += '<span class="type-dot" style="background:' + color + '"></span>';
    html += '<div class="popup-item-content">';
    html += '<a href="' + escapeHtml(o.url) + '" target="_blank" title="'
      + escapeHtml(o.title) + '">' + escapeHtml(o.title) + '</a>';
    var parts = [escapeHtml(o.organization)];
    if (o.date) parts.push(escapeHtml(o.date));
    if (o.time) parts.push(escapeHtml(o.time));
    html += '<div class="popup-meta">' + parts.join(' &middot; ') + '</div>';
    html += '</div></div>';
  });
  if (p.opportunities.length > 15) {
    html += '<div class="popup-more">+ ' + (p.opportunities.length - 15) + ' more</div>';
  }
  html += '</div></div>';
  return html;
}

// ── Map ─────────────────────────────────────────────────
var map = L.map('map').setView([34.05, -118.25], 10);

// Base tiles without labels (renders below polygons)
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
  subdomains: 'abcd',
  maxZoom: 19
}).addTo(map);

// Labels-only layer (renders above polygons)
map.createPane('labels');
map.getPane('labels').style.zIndex = 650;
map.getPane('labels').style.pointerEvents = 'none';
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png', {
  pane: 'labels',
  subdomains: 'abcd',
  maxZoom: 19
}).addTo(map);

// ── State ───────────────────────────────────────────────
var currentLayer = null;
var layerLookup = {};

var activeTypes = new Set(Object.keys(TYPE_COLORS));
var orgSearch = '';
var upcomingOnly = false;

// ── Build type filter checkboxes ────────────────────────
var typeFiltersEl = document.getElementById('type-filters');
Object.entries(TYPE_COLORS).forEach(function(entry) {
  var type = entry[0], color = entry[1];
  var label = document.createElement('label');
  var cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = true;
  cb.dataset.type = type;
  cb.addEventListener('change', function() {
    if (cb.checked) activeTypes.add(type);
    else activeTypes.delete(type);
    applyFilters();
  });
  var dot = document.createElement('span');
  dot.className = 'type-dot';
  dot.style.background = color;
  label.appendChild(cb);
  label.appendChild(dot);
  label.appendChild(document.createTextNode(' ' + type));
  typeFiltersEl.appendChild(label);
});

// ── Org search with debounce ────────────────────────────
var orgSearchTimeout;
document.getElementById('org-search').addEventListener('input', function() {
  var self = this;
  clearTimeout(orgSearchTimeout);
  orgSearchTimeout = setTimeout(function() {
    orgSearch = self.value.trim().toLowerCase();
    applyFilters();
  }, 200);
});

document.getElementById('upcoming-only').addEventListener('change', function() {
  upcomingOnly = this.checked;
  applyFilters();
});

document.getElementById('reset-filters').addEventListener('click', function() {
  activeTypes.clear();
  Object.keys(TYPE_COLORS).forEach(function(t) { activeTypes.add(t); });
  document.querySelectorAll('#type-filters input').forEach(function(cb) { cb.checked = true; });
  document.getElementById('org-search').value = '';
  orgSearch = '';
  document.getElementById('upcoming-only').checked = false;
  upcomingOnly = false;
  applyFilters();
});

// ── Sidebar toggle ──────────────────────────────────────
document.getElementById('sidebar-toggle').addEventListener('click', function() {
  document.getElementById('sidebar').classList.toggle('collapsed');
  setTimeout(function() { map.invalidateSize(); }, 350);
});

if (window.innerWidth <= 768) {
  document.getElementById('sidebar').classList.add('collapsed');
}

// ── Virtual section toggle ──────────────────────────────
document.getElementById('virtual-header').addEventListener('click', function() {
  document.getElementById('virtual-section').classList.toggle('collapsed');
});

// ── Render virtual opps list ────────────────────────────
var virtualListEl = document.getElementById('virtual-list');
virtualOpps.forEach(function(o) {
  var div = document.createElement('div');
  div.className = 'virtual-item';
  var a = document.createElement('a');
  a.href = o.url || '#';
  a.target = '_blank';
  a.textContent = o.title;
  var orgDiv = document.createElement('div');
  orgDiv.className = 'v-org';
  orgDiv.textContent = o.organization;
  div.appendChild(a);
  div.appendChild(orgDiv);
  virtualListEl.appendChild(div);
});

// ── Filter logic ────────────────────────────────────────
function filterOpps(opps) {
  return opps.filter(function(o) {
    if (!activeTypes.has(o.type)) return false;
    if (orgSearch && o.organization.toLowerCase().indexOf(orgSearch) === -1) return false;
    if (upcomingOnly && (!o.date || o.date === 'Ongoing')) return false;
    return true;
  });
}

// ── Choropleth render ───────────────────────────────────
function applyFilters() {
  if (currentLayer) map.removeLayer(currentLayer);
  layerLookup = {};

  var filteredFeatures = [];
  var totalFiltered = 0;

  allData.features.forEach(function(f) {
    var filtered = filterOpps(f.properties.opportunities);
    if (filtered.length > 0) {
      filteredFeatures.push({
        type: 'Feature',
        geometry: f.geometry,
        properties: {
          zipcode: f.properties.zipcode,
          count: filtered.length,
          opportunities: filtered
        }
      });
      totalFiltered += filtered.length;
    }
  });

  var maxCount = filteredFeatures.length > 0
    ? Math.max.apply(null, filteredFeatures.map(function(f) { return f.properties.count; }))
    : 1;

  currentLayer = L.geoJSON(
    {type: 'FeatureCollection', features: filteredFeatures},
    {
      style: function(feature) {
        var ratio = feature.properties.count / maxCount;
        return {
          fillColor: getColor(ratio),
          weight: 1.5,
          opacity: 1,
          color: '#fff',
          fillOpacity: 0.45
        };
      },
      onEachFeature: function(feature, layer) {
        var p = feature.properties;

        // Sticky tooltip follows cursor
        layer.bindTooltip(
          '<strong>' + escapeHtml(p.zipcode) + '</strong>: '
            + p.count + ' opportunit' + (p.count === 1 ? 'y' : 'ies'),
          {sticky: true}
        );

        // Rich popup on click
        layer.bindPopup(buildPopupHtml(p), {maxWidth: 360});

        // Hover highlight
        layer.on({
          mouseover: function(e) {
            e.target.setStyle({
              weight: 3,
              color: '#333',
              fillOpacity: 0.7
            });
            e.target.bringToFront();
          },
          mouseout: function(e) {
            currentLayer.resetStyle(e.target);
          }
        });

        layerLookup[p.zipcode] = layer;
      }
    }
  ).addTo(map);

  // Update header stats
  document.getElementById('stat-total').textContent = totalFiltered;
  document.getElementById('stat-zips').textContent = filteredFeatures.length;
  document.getElementById('legend-max').textContent = maxCount;

  updateSidebarList(filteredFeatures, maxCount, totalFiltered);
}

// ── Sidebar list ────────────────────────────────────────
function updateSidebarList(features, maxCount, total) {
  var sorted = features.slice().sort(function(a, b) {
    return b.properties.count - a.properties.count;
  });

  document.getElementById('zip-list-header').textContent =
    sorted.length + ' zip codes \u00B7 ' + total + ' opportunities';

  var listEl = document.getElementById('zip-list');
  listEl.innerHTML = '';

  if (sorted.length === 0) {
    listEl.innerHTML = '<div class="no-results">No results match your filters.</div>';
    return;
  }

  sorted.forEach(function(f) {
    var p = f.properties;
    var ratio = p.count / maxCount;
    var div = document.createElement('div');
    div.className = 'zip-item';

    var codeSpan = document.createElement('span');
    codeSpan.className = 'zip-code';
    codeSpan.textContent = p.zipcode;

    var barContainer = document.createElement('div');
    barContainer.className = 'zip-bar-container';
    var bar = document.createElement('div');
    bar.className = 'zip-bar';
    bar.style.width = (ratio * 100) + '%';
    bar.style.background = getColor(ratio);
    barContainer.appendChild(bar);

    var countSpan = document.createElement('span');
    countSpan.className = 'zip-count';
    countSpan.textContent = p.count;

    div.appendChild(codeSpan);
    div.appendChild(barContainer);
    div.appendChild(countSpan);

    div.addEventListener('click', function() {
      var layer = layerLookup[p.zipcode];
      if (layer) {
        map.fitBounds(layer.getBounds(), {maxZoom: 14, padding: [50, 50]});
        setTimeout(function() { layer.openPopup(); }, 500);
      }
      document.querySelectorAll('.zip-item.active').forEach(function(el) {
        el.classList.remove('active');
      });
      div.classList.add('active');
    });

    listEl.appendChild(div);
  });
}

// ── Initial render ──────────────────────────────────────
applyFilters();
</script>
</body>
</html>"""


def generate_html(geojson: dict, virtual_opps: list[dict]) -> str:
    """Generate the complete interactive HTML map."""
    geojson_str = json.dumps(geojson)
    virtual_list = [
        {
            "title": o["title"],
            "organization": o["organization"],
            "date": o.get("date", ""),
            "type": o.get("opportunity_type", ""),
            "url": o.get("opportunity_url", ""),
        }
        for o in virtual_opps
    ]
    virtual_json = json.dumps(virtual_list)

    total_mapped = sum(f["properties"]["count"] for f in geojson["features"])
    total_zips = len(geojson["features"])
    virtual_count = len(virtual_opps)
    max_count = max(
        (f["properties"]["count"] for f in geojson["features"]), default=1
    )

    return (
        HTML_TEMPLATE.replace("__GEOJSON_DATA__", geojson_str)
        .replace("__VIRTUAL_DATA__", virtual_json)
        .replace("__TOTAL_MAPPED__", str(total_mapped))
        .replace("__TOTAL_ZIPS__", str(total_zips))
        .replace("__VIRTUAL_COUNT__", str(virtual_count))
        .replace("__MAX_COUNT__", str(max_count))
    )


def main():
    by_zip, virtual = group_by_zip(CSV_PATH)
    total = sum(len(v) for v in by_zip.values()) + len(virtual)
    print(f"Found {len(by_zip)} zip codes, {len(virtual)} virtual, {total} total opportunities")

    for zc, opps in sorted(by_zip.items(), key=lambda x: -len(x[1]))[:10]:
        print(f"  {zc}: {len(opps)}")

    boundaries = download_boundaries()
    geojson = build_choropleth_geojson(by_zip, boundaries)
    print(f"Matched {len(geojson['features'])}/{len(by_zip)} zip codes to boundaries")

    html = generate_html(geojson, virtual)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Map saved to {HTML_PATH}")


if __name__ == "__main__":
    main()
