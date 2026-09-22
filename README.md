# Rommel Sorteren

Samen foto's van spullen categoriseren: kringloop, bewaren, weggeven, of grofvuil.
Alles draait lokaal op de eigen VPS — foto's en database blijven volledig intern,
geen externe opslag nodig.

## Hoe het werkt

- Ayla en Jurian loggen in met hun naam + hetzelfde wachtwoord.
- Op "Foto toevoegen" maak je een foto (camera van je telefoon via de browser),
  geef je 'm optioneel een naam/tags (bv. "beker, keuken") en upload je 'm —
  direct opgeslagen op de server, geen tussenstap nodig.
- Op "Foto's categoriseren" kies je per foto een categorie (of maak zelf een
  nieuwe categorie aan).
- Kiezen jullie hetzelfde: de foto staat definitief bij "Resultaten".
- Kiezen jullie verschillend: de foto komt in "Het overleg" te staan, waar je
  de keuze van je partner kan overnemen of opnieuw kan kiezen.
- Op "Zoeken" vind je een foto terug op naam/tag, ook als je 'm pas achteraf
  een naam gegeven hebt (kan overal waar een foto verschijnt).

## Stap 1 — Bestanden klaarzetten op de VPS

```bash
git clone https://github.com/jmmreckman/rommel-sorteren.git
cd rommel-sorteren
cp .env.example .env
```

Vul in `.env` een `SITE_PASSWORD` in — het wachtwoord dat jullie allebei
gebruiken om in te loggen (los van de naamkeuze Ayla/Jurian).

## Stap 2 — Draaien met Docker

```bash
docker compose up -d --build
```

Test lokaal of het werkt: `curl http://127.0.0.1:8123/health` moet
`{"ok":true}` teruggeven.

## Stap 3 — rommel.steenhub.nl aan elkaar knopen

Deze VPS gebruikt geen nginx, maar **Caddy** (draait als container, regelt
HTTPS-certificaten automatisch). Het gedeelde Caddyfile staat op
`/opt/kamerverhuur-scanner/deploy/Caddyfile`.

1. **DNS**: voeg bij je domeinregistrar een CNAME- of A-record toe voor
   `rommel` naar hetzelfde adres als steenhub.nl (zie `caddy-snippet.example`
   voor de achtergrond).
2. **Netwerk**: dit project moet op hetzelfde Docker-netwerk draaien als
   Caddy (`deploy_default`) — dat staat al in `docker-compose.yml`.
3. **Caddyfile bijwerken**: voeg het blok uit `caddy-snippet.example` toe aan
   `/opt/kamerverhuur-scanner/deploy/Caddyfile`, en herlaad Caddy zonder
   downtime voor de andere sites:
   ```bash
   docker exec deploy-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
   ```

Klaar — rommel.steenhub.nl zou nu moeten werken (Caddy haalt vanzelf een
Let's Encrypt-certificaat op zodra het DNS-record actief is).

## Dagelijks gebruik

- Nieuwe foto's toevoegen: via "Foto toevoegen" in de app zelf.
- Logs bekijken bij problemen: `docker compose logs -f`
- App bijwerken na een wijziging in de code:
  ```bash
  git pull && docker compose up -d --build
  ```
  (geen auto-deploy, dit draai je zelf na elke wijziging)

## Lokaal ontwikkelen / testen (zonder Docker)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export SITE_PASSWORD=test
uvicorn app.main:app --reload
```

Ga naar `http://localhost:8000`.
