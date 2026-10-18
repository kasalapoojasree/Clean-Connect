/* CleanConnect - Leaflet maps (main map + location picker on the report form) */
const SEV_COLOR = { Low: '#2e9d63', Medium: '#f2b705', High: '#f07c1b', Critical: '#d62828' };
const SEV_RADIUS = { Low: 7, Medium: 9, High: 12, Critical: 15 };
const OSM = { url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
              attr: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' };

function markerStyle(r) {
  const resolved = r.status === 'Resolved';
  return { radius: SEV_RADIUS[r.severity] || 8, fillColor: resolved ? '#8fa89a' : (SEV_COLOR[r.severity] || '#2e9d63'),
           color: resolved ? '#146c3c' : '#ffffff', weight: resolved ? 3 : 2, dashArray: resolved ? '3 3' : null,
           fillOpacity: resolved ? 0.55 : 0.9 };
}

async function initMainMap() {
  const map = L.map('map').setView([20.59, 78.96], 5);
  L.tileLayer(OSM.url, { attribution: OSM.attr, maxZoom: 19 }).addTo(map);
  const layer = L.layerGroup().addTo(map);
  let data = [];
  try {
    const res = await fetch('/api/map-data');
    data = await res.json();
  } catch (e) { document.getElementById('mapStatus').textContent = 'Could not load map data.'; return; }

  function draw() {
    layer.clearLayers();
    const status = document.getElementById('statusFilter').value, sev = document.getElementById('sevFilter').value;
    const shown = data.filter(r => (!status || r.status === status) && (!sev || r.severity === sev));
    shown.forEach(r => {
      const m = L.circleMarker([r.latitude, r.longitude], markerStyle(r));
      const link = r.url ? `<br><a href="${esc(r.url)}">View details</a>` : '';
      m.bindPopup(`<strong>${esc(r.complaint_id)}</strong><br>${esc(r.title)}<br>
        Category: ${esc(r.category)}<br>Severity: ${esc(r.severity)}<br>Status: ${esc(r.status)}<br>
        Date: ${esc(r.created_at)}${link}`);
      layer.addLayer(m);
    });
    document.getElementById('mapStatus').textContent = shown.length
      ? `${shown.length} complaint${shown.length > 1 ? 's' : ''} shown`
      : 'No complaints with coordinates match this filter.';
    if (shown.length) map.fitBounds(L.latLngBounds(shown.map(r => [r.latitude, r.longitude])).pad(0.3), { maxZoom: 15 });
  }
  document.getElementById('statusFilter').addEventListener('change', draw);
  document.getElementById('sevFilter').addEventListener('change', draw);
  draw();

  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = () => {
    const d = L.DomUtil.create('div', 'legend');
    d.innerHTML = Object.entries(SEV_COLOR).map(([k, c]) => `<div><i style="background:${c}"></i>${k}</div>`).join('') +
      '<div><i style="background:#8fa89a;border:2px dashed #146c3c"></i>Resolved</div>';
    return d;
  };
  legend.addTo(map);
}

/* Location picker on report form */
let pickerMap, pickerMarker;
function initPickerMap() {
  const el = document.getElementById('pickerMap');
  if (!el) return;
  pickerMap = L.map('pickerMap').setView([20.59, 78.96], 5);
  L.tileLayer(OSM.url, { attribution: OSM.attr, maxZoom: 19 }).addTo(pickerMap);
  pickerMap.on('click', e => setPickedLocation(e.latlng.lat, e.latlng.lng, false));
  const lat = parseFloat(document.getElementById('latitude').value), lng = parseFloat(document.getElementById('longitude').value);
  if (!isNaN(lat) && !isNaN(lng)) setPickedLocation(lat, lng, true);
  ['latitude', 'longitude'].forEach(id => document.getElementById(id).addEventListener('change', () => {
    const a = parseFloat(document.getElementById('latitude').value), b = parseFloat(document.getElementById('longitude').value);
    if (!isNaN(a) && !isNaN(b)) setPickedLocation(a, b, true);
  }));
}
function setPickedLocation(lat, lng, zoom) {
  document.getElementById('latitude').value = lat.toFixed(6);
  document.getElementById('longitude').value = lng.toFixed(6);
  if (!pickerMap) return;
  if (pickerMarker) pickerMarker.setLatLng([lat, lng]); else pickerMarker = L.marker([lat, lng]).addTo(pickerMap);
  if (zoom) pickerMap.setView([lat, lng], 16);
}
