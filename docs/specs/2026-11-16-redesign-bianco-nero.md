# Redesign dell'interfaccia — "Bianco e nero"

Approvato sul mockup il 2026-11-16. I mockup di riferimento (HTML statico, una schermata per file)
sono in `docs/design-reference/redesign/`: sono **la fonte di verità visiva**. Aprirli e leggerne
markup e stili: misure, colori, ordine dei controlli e testi vanno ripresi da lì.

| Mockup | Schermata dell'app |
|---|---|
| `Home.dc.html` / `HomeLight.dc.html` | tab Trascrizione, stato iniziale (`ui/home_widget.py`) |
| `Progress.dc.html` / `ProgressLight.dc.html` | tab Trascrizione, in corso (`ui/progress_widget.py`) |
| `Result.dc.html` / `ResultLight.dc.html` | tab Trascrizione, completata (`ui/result_widget.py`) |
| `Main.dc.html` / `EditorLight.dc.html` | tab Editor (`workspace`, `preview_area`, `waveform_widget`, `transport_bar`, `subtitle_timeline`, `inspector_widget`) + dialog Trova e sostituisci |
| `Export.dc.html` / `ExportLight.dc.html` | tab Esportazione (`ui/export_tab.py`) |
| `System.dc.html` | token, tipografia, componenti, regole |

## Perché

L'interfaccia attuale ha l'aspetto di un prodotto generato: sfondo "aurora" sfumato, titolo da
landing page, colonna stretta centrata, accento blu-viola, card arrotondate ovunque, etichette in
maiuscoletto, glifi di testo al posto delle icone. Il proprietario vuole uno strumento
professionale da sala di montaggio.

## Vincolo assoluto

**Tasti, flussi, scorciatoie e funzioni restano invariati.** Ogni controllo esistente resta, con
la stessa azione, lo stesso segnale e la stessa scorciatoia. Cambiano solo aspetto, densità e
disposizione dentro le stesse schermate. Tutti i test esistenti devono restare verdi (adeguando
solo quelli che verificano testi o strutture visive cambiate di proposito).

## Sistema

**Colore** (token in `ui/theme.py`; i nomi dei token esistenti restano, cambiano i valori; i token
"aurora"/viola spariscono):

| Ruolo | Scuro | Chiaro |
|---|---|---|
| Fondo (area di lavoro, campi) | `#141414` | `#f4f4f4` |
| Pannello (barre, ispettore, log) | `#1b1b1b` | `#ffffff` |
| Rialzo (controllo premuto, blocchi) | `#262626` | `#e8e8e8` |
| Linea | `#303030` | `#d4d4d4` |
| Testo | `#f2f2f2` | `#141414` |
| Secondario | `#a6a6a6` | `#595959` |
| Etichetta | `#8c8c8c` | `#6b6b6b` |
| Accento (cursore, selezione, primario) | `#ffffff` | `#141414` |
| Testo su accento | `#141414` | `#ffffff` |
| Selezione riga | `#2e2e2e` | `#e4e4e4` |
| Forma d'onda | `#5c5c5c` | `#b3b3b3` |
| Errore | `#f2706b` | `#b92f2a` |
| Avviso | `#f0a63c` | `#8f5400` |

Il colore compare **solo** per errori e avvisi, sempre con un'icona o una parola accanto.

**Tipografia**: IBM Plex Sans (400/500/600) per l'interfaccia, IBM Plex Mono (400/500) per
timecode, tempi, numeri, log e scorciatoie; cifre tabulari. I font vanno inclusi in
`app/assets/fonts/` (licenza OFL, con il file di licenza) e caricati all'avvio con
`QFontDatabase`; `platform_support.font_stack_ui/mono` li mette per primi e tiene i font di
sistema come ripiego. Scala: 22 px titoli di stato, 20 px timecode, 14 px testo dei sottotitoli,
13 px interfaccia, 11–12 px etichette. Nessuna etichetta in maiuscolo.

**Forma**: raggio 4 px sui controlli, 0 su pannelli e righe, 6 px solo su zona di rilascio e
dialog. Pannelli separati da una linea di 1 px, mai card con ombra. Nessuna sfumatura, nessuna
animazione di sfondo (l'`AuroraMixin` viene rimosso). Interruttori rettangolari (38×20, raggio 3).

**Icone**: tratto 1.6 px, 16 px, disegnate da noi (path SVG nei mockup) in un modulo
`ui/icons.py` che le rende nel colore del tema; nessun glifo di testo (↩ ÷ ⊔ × ★ ☾ ▶ ■) e nessuna
icona di sistema.

## Struttura delle schermate

- **Intestazione, una sola riga da 40 px**: tab dei progetti a sinistra (nome, punto "modifiche
  non salvate", chiudi, "+"), le tre sezioni Trascrizione / Editor / Esportazione al centro
  (senza numeri; lucchetto quando bloccate, punto quando l'editor contiene sottotitoli), tema a
  destra. Oggi sono due righe: vanno fuse senza perdere alcun controllo.
- **Schermata iniziale**: a sinistra "Sorgente" (zona di rilascio a tutta larghezza, o riga del
  file caricato con "Cambia") e sotto "Recenti" come elenco (nome, cartella, dimensione); a
  destra, pannello da 420 px con le impostazioni (Modello Whisper con RAM e qualità, Lingua,
  Filtro VAD, Alta precisione), riepilogo, Stima e "Avvia trascrizione". Nessun titolo
  promozionale. L'avviso dipendenze è una riga sopra il contenuto, solo quando serve.
- **In corso**: a sinistra file e impostazioni, percentuale grande in monospazio, barra sottile,
  elenco delle cinque fasi (ricavato dai messaggi di stato già esistenti), "Interrompi"; a destra
  pannello "Log" da 520 px con orario per riga e "Copia log".
- **Completata**: fascia con esito, conteggio, avviso "Versione modificata nell'editor", e le tre
  azioni (Nuova trascrizione, Esporta SRT, Apri nell'editor); sotto, anteprima a tabella.
- **Editor**: in alto monitor video (sinistra, 452 px) e forma d'onda con righello e corsia dei
  blocchi (destra) affiancati; riga di trasporto (riproduci, ferma, timecode grande, posizione,
  volume, velocità, ripeti, J K L); barra strumenti con icona + testo + scorciatoia; tabella a
  sinistra e Ispettore a destra (324 px); barra di stato.
- **Esportazione**: fascia informativa; a sinistra "Salva file" e "Pubblica direttamente" come
  righe (sigla, titolo, descrizione); a destra "Anteprima SRT" in monospazio.
- **Trova e sostituisci**: dialog compatto; il contatore dei risultati non è più una riga a sé ma
  compare dentro il campo "Trova", a destra, in forma breve ("1 di 3", "Nessun risultato").

## Decisioni prese dal progettista (da confermare a lavoro visto)

- Monitor video e forma d'onda visibili insieme (oggi si alternano).
- Contatore di Trova e sostituisci spostato dentro il campo invece che eliminato, per non perdere
  l'informazione.
- Orario accanto alle righe del log ed elenco delle fasi: solo presentazione di dati già esistenti.

## Fuori ambito

Nuove funzioni, nuove scorciatoie, cambi a `engine.py` o a `core/` (salvo i colori del modello
tabella, che passano già dai token).
