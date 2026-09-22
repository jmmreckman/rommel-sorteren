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

// Om de tien keuzes een leuk, wegklikbaar bemoedigingskaartje - roulerend
// door een vaste lijst, weer van voren af aan zodra hij op is.
const MIJLPAAL_BERICHTEN = [
  'Lekker bezig! 💪🔥',
  'Love you long time! 😘💕',
  'Met dit tempo hebben we over een half jaar een lege zolder 🏠✨',
  'Je bent op dreef! 🚀',
  'Heerlijk wat een keuzes worden hier gemaakt 🙌',
  'Toppertje, hou van jou ❤️',
  'Lowen heeft gepoept 💩😂',
  'Kusje 😘',
  'Vergeet niet wat te drinken tussendoor 🥤',
];

function toonMijlpaal(totalChoices) {
  if (!totalChoices || totalChoices % 10 !== 0) return;
  const index = (totalChoices / 10 - 1) % MIJLPAAL_BERICHTEN.length;
  const overlay = document.createElement('div');
  overlay.className = 'mijlpaal-overlay';
  overlay.innerHTML = `
    <div class="mijlpaal-kaart">
      <div class="mijlpaal-teller">🎉 ${totalChoices} keuzes gemaakt!</div>
      <div class="mijlpaal-bericht">${MIJLPAAL_BERICHTEN[index]}</div>
      <button class="btn">Doorgaan</button>
    </div>
  `;
  const sluiten = () => overlay.remove();
  overlay.querySelector('button').addEventListener('click', sluiten);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) sluiten(); });
  document.body.appendChild(overlay);
}
