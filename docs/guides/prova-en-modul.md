# Prova en modul på tio minuter

Syfte: gå från ett klonat kit till en modul du är inloggad i, på din egen dator.
Läs detta när: du är med på en workshop och vill bygga en egen modul.
Hör ihop med: [README](../../README.md), [new module](new-module.md), [mallens README](../../template/README.md).

Assistenter och ytor är grunden i Eneo, och de byggs utan kod. En modul är ett frivilligt nästa steg för den som behöver ett eget gränssnitt och egen logik.

## Du behöver

- Git, Node 22.22.2 eller senare (`node --version`) och Python 3.12 eller senare.
- macOS, Linux eller Windows.
- Ingen Eneo-instans: mallen har en låtsas-Eneo, en "stub".

## Kommandon

```bash
git clone https://github.com/eneo-ai/eneo-module-kit.git
cd eneo-module-kit
node scripts/new-module.mjs ../eneo-mod-example
cd ../eneo-mod-example
node stub-eneo/dev.mjs --check
node stub-eneo/dev.mjs
```

## Det här ska du se

1. `new-module.mjs` tar en eller ett par minuter och slutar med `The module is in ...`.
2. `--check` slutar med `OK: signed in through the stub Eneo, the page is served, and /api/example answered {"greeting":"Hej Erik Lund"}`.
3. `node stub-eneo/dev.mjs` startar modulen. Öppna http://localhost:3001 och tryck på "Logga in med Eneo". Sidan "Välj ett flöde" visar "Hej Erik Lund" och två flöden. Ctrl+C stoppar.

## Låt din agent bygga vidare

Starta Claude Code eller Codex i modulens mapp. `CLAUDE.md`, `AGENTS.md` och en skill finns redan där. Till exempel:

> Lägg till en sida "Om modulen" med en rubrik och en kort text, länka till den från startsidan och kör testerna.

Läs det agenten skrev och prova själv i webbläsaren.

## Om det inte fungerar

Se [When it does not work](new-module.md#when-it-does-not-work) (på engelska). Installera inte paketen från releasen `v0.1.0`: den passar inte mallen. Upptagen port: `node stub-eneo/dev.mjs --port 3002 --stub-port 8412`.

## Läs vidare

- [New module](new-module.md): döp om modulen, tester, image, CI.
- [Build a module](build-a-module.md) och [UI package](ui-package.md).
- En riktig Eneo kräver en administratör: modulnyckel, callback-adress och servicenyckel.
