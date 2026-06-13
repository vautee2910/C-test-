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
| HGB-Konzept-Synonyme („Sachanlagen" → `sachanlagen`, GuV-/Bilanz-Gliederung) | *kommt als geteilte Config* (`config/hgb_concepts.yaml`) | ⬜ nächster Schritt |

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

## Was bewusst NICHT hier ist

Das Mapping Label → kanonisches HGB-Konzept (`Fact.concept`) braucht die
geteilte HGB-Wissensbasis und ist der nächste Schritt — ebenfalls generalisiert,
nicht pro Firma.
