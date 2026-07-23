// Shared helpers
document.addEventListener('DOMContentLoaded', () => {
  // mark active sidebar link
  const path = location.pathname;
  document.querySelectorAll('.sidebar a').forEach(a => {
    if (a.getAttribute('href') === path) a.classList.add('active');
  });
});

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {})
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}
async function apiGet(url) {
  const res = await fetch(url);
  return { ok: res.ok, status: res.status, data: await res.json().catch(() => ({})) };
}
