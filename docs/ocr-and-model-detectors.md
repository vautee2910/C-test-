# OCR-Stufe & modellbasierte Detektoren

Zwei optionale, **rein lokale** Bausteine, die die bestehende Kette ergänzen,
ohne sie zu verändern:

1. **OCR-Vorstufe** – macht *gescannte* Abschlüsse (ohne Text-Layer) durchsuchbar,
   damit der geometrische Extraktor unverändert greift.
2. **Modellbasierte Detektoren** – deutsches spaCy-NER als zusätzliche
   `Detector`-Schicht, um den Recall der Anonymisierung zu heben.

Beide brauchen Netzwerkzugriff **nur einmalig** für Installation/Modell-Download;
zur Laufzeit (Inferenz) verlassen keine Mandantendaten den Rechner.

---

## 1. OCR-Vorstufe (`fsx.parsing.ocr`, `fsx.parsing.text_layer`)

### Idee
Ein gescannter Abschluss ist eine Bild-PDF ohne Text-Layer – der Extraktor sieht
nichts. Die OCR-Vorstufe erzeugt eine *durchsuchbare* PDF (gleiche Seiten/Koordinaten
plus unsichtbarer Text-Layer), die dann durch den **unveränderten** `PyMuPDFParser`
läuft.

### Gate / Fallback
`ensure_searchable_pdf()` entscheidet pro Dokument:

- **Text-Layer vorhanden → kein OCR.** Die Originaldatei wird unverändert
  zurückgegeben (`OcrOutcome.ocr_applied == False`).
- **Kein/zu wenig Text-Layer → OCR.** Das Backend (Standard: OCRmyPDF/Tesseract)
  erzeugt eine durchsuchbare PDF.

Die Entscheidung ist eine erklärbare, modellfreie Heuristik über die
Zeichenanzahl pro Seite (`fsx.parsing.text_layer`): eine Seite „hat Text", wenn
sie ≥ `min_chars_per_page` (Default 16) extrahierbare Zeichen liefert; das
Dokument „hat einen Text-Layer", wenn der Anteil solcher Seiten ≥
`min_page_coverage` (Default 0.5) ist. Beide Schwellen sind Parameter.

Gemischte Dokumente (einzelne Scan-Seiten in einer digitalen PDF) deckt OCRmyPDF
mit `skip_text=True` ab: nur Seiten ohne Text-Layer werden ge-OCR-t, der Rest
bleibt byte-genau erhalten.

### Interface
```python
class OcrBackend(Protocol):
    def is_available(self) -> bool: ...
    def ocr_to_pdf(self, src: Path, dst: Path) -> Path: ...
```
Damit ist die OCR-Engine austauschbar (OCRmyPDF/Tesseract heute, Docling-OCR o. ä.
später), ohne den Parser anzufassen.

### Nutzung
```python
from fsx.config import load_anonymizer
from fsx.parsing import parse_pdf_with_ocr

raw = parse_pdf_with_ocr(
    "scan.pdf",
    anonymizer=load_anonymizer("config/known_entities.yaml"),
    document_id="DOC1", company_id="C1", fiscal_year=2023,
)
# Digitale PDFs werden direkt geparst; Scans transparent vorher ge-OCR-t.
# raw.source_filename zeigt weiterhin auf die Originaldatei.
```

### Installation (einmalig)
OCRmyPDF ist ein pip-Paket, braucht aber die **System-Binaries** Tesseract und
Ghostscript (nicht pip-installierbar):
```bash
apt-get install -y tesseract-ocr tesseract-ocr-deu ghostscript
pip install ocrmypdf
```
Ohne diese Binaries liefert `OcrMyPdfBackend.is_available()` `False`; wird dann
ein Scan eingereicht, hebt `ensure_searchable_pdf()` einen klaren `OcrError`.

---

## 2. Modellbasierte Detektoren (`fsx.anonymize.model_detectors`)

### Idee
Regex + Dictionary sind präzise, finden aber nur *bekannte* oder *strukturierte*
Entitäten. Ein statistisches NER-Modell hebt den **Recall**: Personen-, Firmen-
und Ortsnamen, die nie im Engagement-Dictionary standen – ohne firmenspezifischen
Code.

### `SpacyNerDetector`
Implementiert das `Detector`-Protokoll über eine spaCy-Pipeline:

- **Lokal:** Inferenz ohne Netzwerk; nur der einmalige Modell-Download braucht
  Egress (siehe `network-allowlist.md`).
- **Injizierbar:** nimmt ein fertiges `nlp`-Callable; `import spacy` passiert erst
  in `SpacyNerDetector.load()`. Dadurch sind die Tests offline (Fake-Pipeline).
- **Label-Mapping:** spaCy `PER→PERSON`, `ORG→COMPANY`, `LOC/GPE→LOCATION`;
  `MISC` wird verworfen (in Finanzprosa zu unpräzise).
- **Überlappungs-Priorität:** Modell-Spans tragen `PRIORITY_MODEL` (unter
  Dictionary und Regex). Bei gleich langer Überlappung gewinnt also immer die
  kuratierte/strukturierte Schicht; das Modell ergänzt nur *neue* Treffer. Ein
  längerer Modell-Span (voller Name) schlägt einen kürzeren Dictionary-Alias.

### Konsistenz-Hinweis
Wiederholte Nennungen derselben Oberflächenform gruppieren auf ein Token
(`Globex SE` → `[UNTERNEHMEN_n]`). Eine Entität, die *auch* im Dictionary steht,
wird überall dort, wo beide feuern, zugunsten des Dictionarys aufgelöst – das
Dictionary bleibt der Ort für geteilte Synonyme (Leitprinzip: Recall über
KB-Synonyme, nicht über Spezialfälle).

### Konfiguration (opt-in, Default aus)
```yaml
# config/known_entities.yaml
models:
  spacy:
    enabled: true
    model: de_core_news_lg          # lokales spaCy-Paket
    labels: [PERSON, COMPANY, LOCATION]   # optionaler Label-Filter
    min_length: 2
```
Ohne `models`-Abschnitt verhält sich die Engine exakt wie bisher (nur Dictionary
+ Regex).

### Installation (einmalig)
```bash
pip install spacy
python -m spacy download de_core_news_lg
```

---

## Tests
- `tests/test_text_layer.py`, `tests/test_ocr.py`, `tests/test_parse_ocr.py`:
  Gate-Logik mit Fake-Backend (offline) **plus** echter Scan→Durchsuchbar-Roundtrip
  (übersprungen, wenn Tesseract fehlt).
- `tests/test_model_detectors.py`, `tests/test_config.py`: Mapping/Filter/
  Engine-Komposition mit Fake-Pipeline (offline) **plus** echter
  `de_core_news_lg`-Lauf (übersprungen, wenn das Modell fehlt).

Die „echten" Tests laufen automatisch, sobald Binaries/Modell installiert sind,
und werden sonst sauber übersprungen.
