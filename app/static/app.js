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

async function verwijderFoto(photoId) {
  if (!confirm('Deze foto definitief verwijderen? Dit kan niet ongedaan gemaakt worden.')) {
    return false;
  }
  await api(`/api/photos/${photoId}`, { method: 'DELETE' });
  showToast('Foto verwijderd');
  return true;
}

// Maakt een tags-invoerveld dat vanzelf opslaat: tijdens het typen (na een
// korte pauze), en meteen bij verlaten of Enter. Zo kan een tag nooit meer
// verloren gaan doordat je meteen daarna wegnavigeert.
function maakTagInput(photoId, tags) {
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'tag-edit';
  input.placeholder = 'tags toevoegen...';
  input.value = tags || '';
  input.dataset.lastSaved = tags || '';
  let debounceTimer;
  const opslaan = async () => {
    const nieuw = input.value.trim();
    if (nieuw === input.dataset.lastSaved) return;
    try {
      await api(`/api/photos/${photoId}/tags`, { method: 'PATCH', body: JSON.stringify({ tags: nieuw }) });
      input.dataset.lastSaved = nieuw;
      showToast('Tags opgeslagen');
    } catch (e) {
      showToast('Opslaan mislukt');
    }
  };
  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(opslaan, 600);
  });
  input.addEventListener('blur', () => { clearTimeout(debounceTimer); opslaan(); });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.blur(); });
  input.addEventListener('click', (e) => e.stopPropagation());
  return input;
}
