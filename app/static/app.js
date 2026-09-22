async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (res.status === 401) {
    location.href = '/login';
    throw new Error('niet ingelogd');
  }
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).error || (await res.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return res.json();
}

function showToast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1600);
}

const CATEGORY_COLORS = ['#4d7ea8', '#4d8a6a', '#c98a3c', '#a8524d', '#6a5acd', '#178a8a', '#8a6d4d', '#4d4d8a'];
function colorForIndex(i) { return CATEGORY_COLORS[i % CATEGORY_COLORS.length]; }
