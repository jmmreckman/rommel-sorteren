# Rommel Sorteren

Samen foto's van spullen categoriseren: kringloop, bewaren, weggeven, of grofvuil.
Foto's staan in een gedeelde Google Drive-map (niet op de server), de app haalt
ze op en maakt er snelle thumbnails van.

## Hoe het werkt

- Ayla en Jurian loggen in met hun naam + hetzelfde wachtwoord.
- Op "Foto's categoriseren" kies je per foto een categorie (of maak zelf een
  nieuwe categorie aan).
- Kiezen jullie hetzelfde: de foto staat definitief bij "Resultaten".
- Kiezen jullie verschillend: de foto komt in "Het overleg" te staan, waar je
  de keuze van je partner kan overnemen of opnieuw kan kiezen.
- Nieuwe foto's die je later aan de Drive-map toevoegt, verschijnen vanzelf
  (automatische sync elke 15 minuten, of direct via de "Ververs"-knop).

## Stap 1 — Google Drive-map + service account

1. Maak in Google Drive een map aan, bv. "Rommel foto's", en zet daar (of
   later steeds meer) foto's in.
2. Ga naar [Google Cloud Console](https://console.cloud.google.com/), maak
   een nieuw project aan (of gebruik een bestaand project).
3. Zoek naar **"Google Drive API"** en klik op **Enable**.
4. Ga naar **IAM & Admin → Service Accounts → Create Service Account**. Naam
   maakt niet uit, bv. `rommel-sorteren`. Rollen kun je overslaan.
5. Open de aangemaakte service account → tabblad **Keys** → **Add Key →
   Create new key → JSON**. Dit downloadt een `credentials.json` bestand.
6. Open het downloaded JSON-bestand en kopieer het `client_email`-adres
   (ziet eruit als `rommel-sorteren@jouwproject.iam.gserviceaccount.com`).
7. Ga terug naar de Drive-map, klik **Delen**, en deel de map met dat
   e-mailadres als **Viewer** (alleen lezen is genoeg).
8. Open de map in de browser en kopieer het stuk uit de URL na
   `/folders/` — dat is je `DRIVE_FOLDER_ID`.

## Stap 2 — Bestanden klaarzetten op de VPS

```bash
git clone https://github.com/jmmreckman/rommel-sorteren.git
cd rommel-sorteren
cp .env.example .env
```

Vul `.env` in:
- `DRIVE_FOLDER_ID` — uit stap 1.8
- `SITE_PASSWORD` — een wachtwoord dat jullie allebei gebruiken om in te
  loggen (los van de naamkeuze Ayla/Jurian)
- `SYNC_INTERVAL_MINUTES` — mag op 15 blijven staan

Zet het gedownloade JSON-sleutelbestand van stap 1.5 in de projectmap onder
de naam `credentials.json` (naast `docker-compose.yml`).

## Stap 3 — Draaien met Docker

```bash
docker compose up -d --build
```

Test lokaal of het werkt: `curl http://127.0.0.1:8123/health` moet
`{"ok":true}` teruggeven.

## Stap 4 — rommel.steenhub.nl aan elkaar knopen

1. **DNS**: zet bij je domeinregistrar (of waar je de DNS van steenhub.nl
   beheert) een A-record voor `rommel` naar het IP-adres van je VPS
   (hetzelfde IP als steenhub.nl gebruikt).
2. **Nginx**: kopieer `nginx.conf.example` naar je nginx sites-config (zie
   commentaar bovenin het bestand voor het pad), en herlaad nginx:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```
3. **HTTPS-certificaat**: als je certbot al gebruikt voor steenhub.nl:
   ```bash
   sudo certbot --nginx -d rommel.steenhub.nl
   ```

Klaar — rommel.steenhub.nl zou nu moeten werken.

## Dagelijks gebruik

- Nieuwe foto's toevoegen: gewoon in de Drive-map zetten, ze verschijnen
  vanzelf binnen 15 minuten (of klik op "Ververs vanuit Drive" op de
  hoofdpagina voor direct).
- Logs bekijken bij problemen: `docker compose logs -f`
- App bijwerken na een wijziging in de code: `git pull && docker compose up -d --build`

## Lokaal ontwikkelen / testen (zonder Docker)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export DRIVE_FOLDER_ID=... SITE_PASSWORD=test GOOGLE_APPLICATION_CREDENTIALS=./credentials.json
uvicorn app.main:app --reload
```

Ga naar `http://localhost:8000`.
