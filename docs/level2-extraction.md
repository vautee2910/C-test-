# Hardcoded vs. generalisiert — die Trennlinie

Leitprinzip: **so wenig wie möglich pro Firma hardcoden.** Was sich von Abschluss
zu Abschluss unterscheidet, gehört in Daten/Config; die Logik bleibt generisch
und skaliert über beliebig viele Jahresabschlüsse.

## 1. Pro Firma / pro Mandat (das Einzige, das wirklich „hardcoded" ist)

| Was | Wo | Warum |
| --- | --- | --- |
| Known-Entities-Dictionary (Firmenname + Aliasse, Tochtergesellschaften, Personen, Orte, Prüfer, Domains) | `config/known_entities.yaml` (gitignored, pro Mandat) | Re-Identifikation läuft über Eigennamen — die kennt nur der Mandant. |

Das ist die Antwort auf deine Frage: **ja, im Wesentlichen reicht pro Firma ein
Dictionary.** Alles andere unten ist entweder geteiltes Wissen (einmal für alle
HGB-Abschlüsse) oder reine generische Logik.

## 2. Geteiltes Wissen (einmal für ALLE deutschen Abschlüsse, nicht pro Firma)

| Was | Wo | Status |
| --- | --- | --- |
| Deutsche Zahlenformate (`1.784.101,83`, Minus vorn/hinten, Klammern) | `fsx/extract/numbers.py` | ✅ fertig |
| HGB-Konzept-Synonyme („Sachanlagen" → `sachanlagen`, GuV-/Bilanz-Gliederung) | `config/hgb_concepts.yaml` (committet, geteilt) | ✅ fertig |

Wichtig: Die HGB-Wissensbasis ist **nicht** pro Firma — sie ist für jeden
HGB-Jahresabschluss gleich und wird einmal gepflegt.

## 3. Reine generische Logik (kein Beispielwissen, keine Konstanten)

`fsx/extract/tables.py` rekonstruiert aus Wort-Koordinaten Zeilen/Spalten —
ohne eine einzige seitenspezifische Zahl:

- **Zeilen** per vertikalem Clustering (`cluster_rows`).
- **Panels** (AKTIVA | PASSIVA) per Konsens-Rinne (`find_column_gutters`): eine
  echte Rinne hat *links eine Zahl* (Ende der Wertspalte) und *rechts Text*
  (nächstes Label) — so wird sie von einer normalen Label→Wert-Lücke
  unterschieden, und einspaltige Seiten werden nie fälschlich gesplittet.
- **Spalten** per Clustering der rechten Kanten der Zahlen (`detect_value_columns`),
  weil Beträge rechtsbündig stehen.

Alle Schwellwerte (`y_tol`, `min_gap`, `min_support` …) sind generische,
einstellbare Parameter mit sinnvollen Defaults — **keine** Koordinaten aus dem
Beispieldokument.

## Validierung am echten Beleg

Getestet am realen DATEV-Bilanzbericht (Musterholz GmbH, 23 Seiten):
AKTIVA- und PASSIVA-Summe rekonstruiert zu identisch `2.740.484,63` — **die
Bilanz geht auf.** Die Tests in `tests/test_tables.py` nutzen echte Koordinaten
als *realistische Fixtures*, nicht als Geschäftslogik.

## Label → HGB-Konzept (fertig)

`fsx/hgb/` bildet jede Position auf ein kanonisches Konzept ab und erzeugt
`Fact`-Objekte (Geschäftsjahr + Vorjahr) — generalisiert, nicht pro Firma:

- **Matcher** (`concepts.py`): Umlaut-Faltung, Aufzählungs-Stripping (`I.`, `1.`,
  `a)`), dann exakt → Präfix → optional Fuzzy. Fuzzy ist **standardmäßig aus**:
  Recall kommt aus dem Erweitern der geteilten Synonyme, nicht aus Rateterei.
- **Statement-Kontext**: Pro Seite wird Bilanz/GuV aus der Überschrift erkannt,
  damit eine GuV-Zeile nicht auf ein Bilanz-Konzept matcht.
- **Spalten-Regel** (`facts.py`): rechteste Spalte = Vorjahr; laufendes Jahr =
  erste belegte der übrigen Spalten (eigener Betrag statt Gruppensumme, die nur
  die Zeile teilt). Umbrochene Labels werden zusammengeführt, echte Unterposten
  (`a) …`) jedoch nicht.

Am echten Beleg: **56 Facts, alle Konfidenz 1.0** (42 Bilanz + 14 GuV),
Geschäftsjahr und Vorjahr — direkt nutzbar für den Mehrjahresvergleich.

## Bekannte, bewusste Grenze

GuV-Gruppensummen, die DATEV auf die Zeile des letzten Unterpostens setzt
(z. B. Summe „sonstige betriebliche Aufwendungen"), werden derzeit nicht als
eigener Fact erfasst — Präzision vor Vollständigkeit. Nachrüstbar, ohne die
generische Geometrie zu ändern.
