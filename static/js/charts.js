/* CleanConnect - analytics charts (Chart.js, data from /api/analytics) */
const GREENS = ['#0d3b2a', '#1b6b46', '#2e9d63', '#6cc08f', '#a9dcc0', '#d3efe0', '#f2b705'];

async function loadCharts() {
  const res = await fetch('/api/analytics');
  if (!res.ok) { document.getElementById('chartError').classList.remove('d-none'); return; }
  const d = await res.json();
  const labels = a => a.map(x => x.label), values = a => a.map(x => x.n);
  const bar = (id, a, color, horizontal) => new Chart(document.getElementById(id), {
    type: 'bar', data: { labels: labels(a), datasets: [{ data: values(a), backgroundColor: color, borderRadius: 6 }] },
    options: { indexAxis: horizontal ? 'y' : 'x', maintainAspectRatio: false, plugins: { legend: { display: false } },
               scales: { [horizontal ? 'x' : 'y']: { beginAtZero: true, ticks: { precision: 0 } } } } });

  bar('chartCategory', d.categories, GREENS[2]);
  new Chart(document.getElementById('chartStatus'), {
    type: 'doughnut',
    data: { labels: Object.keys(d.status), datasets: [{ data: Object.values(d.status), backgroundColor: ['#2e9d63', '#f2b705', '#9aa8a0'] }] },
    options: { maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } } });
  new Chart(document.getElementById('chartMonth'), {
    type: 'line', data: { labels: labels(d.months), datasets: [{ data: values(d.months), borderColor: GREENS[1], backgroundColor: 'rgba(46,157,99,.15)', fill: true, tension: .3 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
  new Chart(document.getElementById('chartSeverity'), {
    type: 'bar', data: { labels: labels(d.severity), datasets: [{ data: values(d.severity), backgroundColor: ['#2e9d63', '#f2b705', '#f07c1b', '#d62828'], borderRadius: 6 }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
  bar('chartVolunteer', d.volunteers, GREENS[1], true);
  bar('chartAreas', d.areas, GREENS[0], true);
}
document.addEventListener('DOMContentLoaded', loadCharts);
