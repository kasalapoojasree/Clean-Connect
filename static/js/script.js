/* CleanConnect - shared behaviour */
document.addEventListener('DOMContentLoaded', () => {
  // Bootstrap validation + loading state on forms
  document.querySelectorAll('form.needs-validation').forEach(form => {
    form.addEventListener('submit', e => {
      const pw = form.querySelector('[name=password]'), cf = form.querySelector('[name=confirm_password]');
      if (pw && cf) cf.setCustomValidity(pw.value === cf.value ? '' : 'Passwords do not match');
      if (!form.checkValidity()) { e.preventDefault(); e.stopPropagation(); }
      else {
        const btn = form.querySelector('button[type=submit]');
        if (btn && !btn.dataset.noLoad) {
          setTimeout(() => { btn.disabled = true; btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Please wait...'; }, 0);
        }
      }
      form.classList.add('was-validated');
    });
  });
  const cf = document.querySelector('[name=confirm_password]');
  if (cf) cf.addEventListener('input', () => cf.setCustomValidity(''));

  // Confirmation dialogs for destructive buttons/forms
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('submit', e => { if (!confirm(el.dataset.confirm)) e.preventDefault(); });
  });

  // Auto-dismiss success alerts
  document.querySelectorAll('.alert-success').forEach(a => setTimeout(() => {
    bootstrap.Alert.getOrCreateInstance(a).close();
  }, 8000));

  initReportForm();
});

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/* Report page: photo preview + live AI preview + "use my location" */
function initReportForm() {
  const input = document.getElementById('photo');
  if (!input) return;
  const preview = document.getElementById('photoPreview');
  const box = document.getElementById('aiPreview');
  const token = document.querySelector('meta[name=csrf-token]').content;

  input.addEventListener('change', async () => {
    const file = input.files[0];
    box.classList.add('d-none');
    preview.classList.add('d-none');
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { input.value = ''; alert('Please choose an image smaller than 5 MB.'); return; }
    preview.src = URL.createObjectURL(file);
    preview.classList.remove('d-none');
    box.classList.remove('d-none');
    box.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Analysing image...';
    const fd = new FormData();
    fd.append('photo', file);
    try {
      const res = await fetch('/api/classify', { method: 'POST', body: fd, headers: { 'X-CSRF-Token': token } });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Could not analyse image.');
      const label = data.mode === 'trained' ? 'Trained Random Forest model' : 'Unknown model mode';
      box.innerHTML = `<div class="small text-muted mb-1"><i class="bi bi-cpu"></i> AI waste classification - ${esc(label)}</div>
        <div class="fs-5 fw-bold text-success">${esc(data.label)}</div>
        <div class="conf-bar my-2"><span style="width:${data.confidence}%"></span></div>
        <div class="small">Confidence: <strong>${data.confidence}%</strong></div>
        <div class="small text-muted mt-2">AI classification is an assistive prediction and may not always be accurate.</div>`;
    } catch (err) {
      box.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-triangle"></i> ${esc(err.message)}</span>`;
    }
  });

  const geoBtn = document.getElementById('geoBtn');
  if (geoBtn) geoBtn.addEventListener('click', () => {
    if (!navigator.geolocation) { alert('Location is not supported by this browser.'); return; }
    geoBtn.disabled = true;
    navigator.geolocation.getCurrentPosition(pos => {
      geoBtn.disabled = false;
      setPickedLocation(pos.coords.latitude, pos.coords.longitude, true);
    }, () => { geoBtn.disabled = false; alert('Could not get your location. Click the map to choose it instead.'); },
    { enableHighAccuracy: true, timeout: 10000 });
  });
}
