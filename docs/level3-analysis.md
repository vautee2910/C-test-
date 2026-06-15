# Level-3: Mehrjahresvergleich & Kennzahlen

Aus den Level-2-`Fact`s (Geschäftsjahr + Vorjahr je Konzept) baut
`fsx/analysis/` die `AnalysisFeature`s: pro Metrik und Jahr ein Wert, die
Veränderung zum Vorjahr (absolut + relativ) und ein Auffälligkeits-Flag.

## Reported-else-computed

Manche Kennzahlen/Summen stehen schon im Abschluss, manche nicht. Der Resolver
nimmt **den berichteten Wert, wenn vorhanden**, sonst baut er ihn aus den
Komponenten nach — und hält in `formula` fest, welcher Weg genutzt wurde
(`"reported"` vs. z. B. `loehne_gehaelter + soziale_abgaben`).

Beispiele (`fsx/analysis/metrics.py`, geteilte HGB-Definitionen, nicht pro Firma):

| Aggregat | Komponenten | berichtet als |
| --- | --- | --- |
| `bilanzsumme` | summe_anlagevermoegen + summe_umlaufvermoegen (+ RAP aktiv) | `bilanzsumme` |
| `personalaufwand` | loehne_gehaelter + soziale_abgaben | `personalaufwand` |
| `materialaufwand` | aufwand_rhb + aufwand_bezogene_leistungen | `materialaufwand` |

Kennzahlen: `eigenkapitalquote`, `anlagenintensitaet`,
`personalaufwandsquote`, `materialaufwandsquote`.

## Flags

Gemessen wird die Veränderung der **Größenordnung** (Magnitude), damit ein
wachsender Kostenposten genauso als `increase` auffällt wie wachsender Umsatz —
das ist der „hidden costs"-Fokus.

- `stable`: |Δ| < `stable_band` (Default 2 %)
- `increase` / `decrease`: darüber, je nach Richtung der Magnitude
- `anomaly`: |Δ| ≥ `anomaly_threshold` (Default 30 %) — große Schwankung in
  **beide** Richtungen, also „bitte ansehen". Schwellen via `AnalysisConfig`.

## Validierung am echten Beleg

DATEV-Bericht (2 Jahre): 70 Features. `bilanzsumme` nachgebaut = berichtete
Summe (2.740.484,63). Radar meldete u. a. Verbindlichkeiten ggü.
Kreditinstituten +34,4 %.

## Qualitäts-Layer: Reconciliation im Report

`fsx.analysis.analyze_facts()` / `analyze_pdf()` liefern statt einer nackten
Feature-Liste einen `AnalysisReport(features, issues)`: `build_features()` bleibt
ein reiner Transform, der Report fährt zusätzlich die Level-2-Plausibilitäts-
prüfung (`fsx.hgb.reconcile`) mit und **taggt jedes betroffene Feature**
(`quality_issue`). `report.ok` / `report.has_errors` fassen den Lauf zusammen.

Geprüft wird (nur gemeldet, nie verändert):
- **Wertkonflikte** (`error`): dasselbe Konzept/Jahr mehrfach mit abweichendem
  Betrag — fängt OCR-Ziffernfehler, die die „erster gewinnt"-Auflösung sonst
  verschluckt.
- **Gebrochene Identitäten** (`warning`): gemeldete Summe ≠ Σ Komponenten
  (Bilanzsumme, Gesamtleistung = Umsatz + Bestandsveränderung, Personal-/
  Materialaufwand) — nur wenn Summe und genug Komponenten vorliegen.
- **Niedrige Konfidenz** (`info`): Facts unter `review_confidence` (Default 0,7)
  — Teil-Absicherung gegen Fehler, die sich nicht duplizieren.

## Grenze

Deltas brauchen ≥ 2 Jahre. Ein Einzelabschluss mit Geschäftsjahr **und**
Vorjahr (wie hier) genügt; über mehrere Abschlüsse hinweg lassen sich die Facts
zu längeren Reihen zusammenführen (gleiche `company_id`/`concept`, mehr Jahre).
