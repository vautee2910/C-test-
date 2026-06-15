# Modularität: wiederverwendbare Bausteine

Zwei Fähigkeiten sind bewusst **domänenfrei** gebaut, damit sie sich aus dieser
Anwendung lösen und in eine andere einsetzen lassen — nicht nur für
Jahresabschlüsse, sondern für beliebige Dokumente:

1. **Anonymisierung** — `fsx.anonymize`
2. **Strukturierte Tabellen-Extraktion aus PDFs** — `fsx.extract`

Beide funktionieren hier voll, hängen aber an **keinem** HGB-/Analyse-Code.

## Abhängigkeitsrichtung (erzwungen durch Tests)

```
fsx.anonymize   (pure stdlib: re)            ── wiederverwendbar
fsx.extract     (nur PyMuPDF in pdf_words)   ── wiederverwendbar
        │  benutzt geometrie/zahlen, optionalen Anonymizer (duck-typed)
        ▼
fsx.hgb         (HGB-Wissen: Konzepte, Facts, Anlagenspiegel, Reconcile)
fsx.analysis    (Kennzahlen, Features, Report)
```

Die Domänenschichten (`hgb`, `analysis`) dürfen nach unten greifen; die
wiederverwendbaren Pakete **nie** nach oben. `tests/test_modularity.py` scannt
die echten Imports und schlägt fehl, sobald `fsx.extract` oder `fsx.anonymize`
auf `fsx.hgb` / `fsx.analysis` / `fsx.schemas` (oder die Anonymisierung) zugreift.

## 1. `fsx.anonymize` — Anonymisierungs-Pipeline

Detektoren → Span-Merge → konsistente Pseudonyme. Reine Standardbibliothek (nur
`re`); die Modell-Detektoren (`SpacyNerDetector`) sind optional und nur aktiv,
wenn spaCy installiert ist.

```python
from fsx.anonymize import Anonymizer, RegexDetector, DictionaryDetector

anon = Anonymizer(detectors=[RegexDetector(...), DictionaryDetector(...)])
result = anon.anonymize("Müller GmbH, Hamburg")   # -> .text, .spans
```

Funktioniert auf **beliebigem Text** (Verträge, Mails, Berichte) — nichts ist
auf Abschlüsse zugeschnitten. Herauslösen = das Verzeichnis `fsx/anonymize/`
kopieren; keine weiteren `fsx`-Importe.

## 2. `fsx.extract` — Tabellen aus PDF-Koordinaten

Generische Geometrie: Wörter → Zeilen → Panels → Wertspalten → `(Label, Werte)`.
Keine dokument­spezifischen Konstanten.

```python
from fsx.extract.pdf_words import extract_tables

# ganz ohne fsx-Domäne, Anonymisierung optional:
tables = extract_tables("irgendein.pdf")                 # roh
tables = extract_tables("doc.pdf", anonymizer=my_anon)   # Labels pseudonymisiert
```

* `fsx.extract.tables` / `fsx.extract.numbers` — **null** externe Abhängigkeiten
  (pure stdlib), direkt testbar ohne PDF.
* `fsx.extract.pdf_words` — der einzige Ort mit PyMuPDF (`fitz`); normalisiert
  Seitenrotation und akzeptiert einen optionalen, **duck-typed** Anonymizer
  (alles mit `anonymize(str).text`, oder `None`).

Die Zuordnung *Tabelle → Bedeutung* (HGB-Konzepte, Anlagenspiegel, `Fact`s)
liegt ausschließlich in `fsx.hgb` — also bleibt `fsx.extract` für jede andere
Tabellen­art nutzbar.

## In eine andere Anwendung einsetzen

* **Nur Geometrie** (eigenes Mapping): `fsx/extract/` übernehmen. Einzige Laufzeit-
  Abhängigkeit ist PyMuPDF (und auch nur in `pdf_words`); `tables.py`/`numbers.py`
  laufen rein mit der Standardbibliothek.
* **Nur Anonymisierung**: `fsx/anonymize/` übernehmen. Reine Standardbibliothek.
* **Beides zusammen**: der optionale Anonymizer in `extract_tables` ist duck-typed,
  also ohne harte Kopplung kombinierbar.

Sauberer nächster Schritt (falls gewünscht): beide Verzeichnisse als eigenständige
Pip-Pakete (`fsx-anonymize`, `fsx-extract`) ausgliedern — die Importgrenzen sind
bereits so geschnitten, dass das nur ein Verschieben plus `pyproject` ist.
