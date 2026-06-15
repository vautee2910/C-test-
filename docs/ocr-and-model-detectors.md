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

Das Standard-Backend (`default_backend()`) läuft mit `force_ocr=True`: es wird
nur aufgerufen, *nachdem* das Dokument-Gate bereits „kein nutzbarer Text-Layer"
entschieden hat, also wird jede Seite neu ge-OCR-t. Das umgeht eine reale Falle —
manche Scans tragen auf einzelnen Seiten einen *Phantom*-Text-Layer (wenige
unsichtbare/Nicht-Unicode-Glyphen), den `skip_text=True` als „hat schon Text"
behandelt und still durchreicht; diese Seiten erreichen den Parser dann ohne
verwertbaren Text (auf einem echten Test-Scan ≈ 46 % Textverlust, inkl. der GuV).
`skip_text=True` bleibt für *echt gemischte* PDFs (Scan-Seiten in einer digitalen
PDF) verfügbar und erhält dort die Digital-Seiten byte-genau — die beiden Modi
schließen sich in OCRmyPDF gegenseitig aus.

> Quergelesen werden Tabellen seitenweise rotationsnormalisiert: quer (Landscape)
> in ein Hochformat-Dokument eingebundene Bilanz-/Anlagenspiegel-Seiten
> (`/Rotate 90`) werden über `page.rotation_matrix` in Leserichtung gebracht,
> bevor die Geometrie sie rekonstruiert. Für aufrechte Seiten ist das die
> Identität.

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

### OCR-Qualität: optionale Stellschrauben (per Default aus)
Das Backend kennt drei Genauigkeits-Knöpfe, die `default_backend()` aus der
Umgebung liest (keine Code-Änderung nötig):

| Env-Variable | Wirkung |
| --- | --- |
| `FSX_TESSDATA_DIR` | Tesseract-Datenverzeichnis (z. B. `tessdata_best` LSTM-Modelle) statt der System-Daten; wird für die Dauer des Aufrufs als `TESSDATA_PREFIX` gesetzt und danach wieder entfernt. Das Verzeichnis muss die `configs`/`tessconfigs`-Hilfsdateien enthalten, nicht nur `*.traineddata`. |
| `FSX_TESSERACT_OEM` | OCR-Engine-Modus (`1` = nur LSTM). |
| `FSX_OCR_OVERSAMPLE` | Ziel-DPI, auf die Seitenbilder vor dem OCR hochgesampelt werden. |

```bash
# tessdata_best (deu/eng) holen und mit den System-Konfigs zusammenführen:
mkdir tessbest && cp -r /usr/share/tesseract-ocr/5/tessdata/* tessbest/
curl -sL -o tessbest/deu.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/deu.traineddata
curl -sL -o tessbest/eng.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata
export FSX_TESSDATA_DIR="$PWD/tessbest" FSX_TESSERACT_OEM=1
```

**Warum aus by default:** Auf beiden echten Testbelegen hat bereits `force_ocr`
allein jede Seite zurückgeholt und die Zahlen korrekt gelesen; `tessdata_best`
verbesserte die End-zu-End-Extraktion *nicht* messbar (eher etwas geringerer
Recall), und `oversample` störte das Layout (verlor auf dem Test-Scan die
komplette GuV) bei ~2,5× Laufzeit. Die Sicherheit gegen verbleibende OCR-Fehler
liefert stattdessen die Plausibilitätsprüfung (`fsx.hgb.reconcile`). Die Knöpfe
bleiben für Korpora verfügbar, auf denen sie nachweislich helfen — **vorher
messen.**

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

### NER-Rauschfilter (für Abschlüsse)
Auf echten Belegen redigierte das allgemeine spaCy-de Statement-Vokabular
(`BILANZ`, `AKTIVA`, `PASSIVA`, …) als Firma und Enumeratoren (`I.`, `II.`) als
Person. Zwei Filter, die den Detektor **domänenfrei** halten:
- **Struktur-Filter** (im Detektor, generisch): verwirft reine Enumeratoren und
  Oberflächen ohne echtes Wort.
- **Stoppwörter** (injiziert): `fsx.config._DEFAULT_NER_STOPWORDS` (Statement-/
  Positions-Vokabular). Gematcht wird die *ganze* Oberfläche, eine Firma, die ein
  solches Wort nur *enthält* („Aktiva Verwaltungs GmbH"), bleibt erhalten.

### `PrivacyFilterDetector` (openai/privacy-filter)
Zweckgebautes PII-Token-Classification-Modell (gpt-oss-artig, 50 M aktive
Parameter, ONNX, Apache-2.0). Stark bei **Personen-/Kontakt-PII** — Person,
Adresse, E-Mail, Telefon, URL, Datum, Kontonummer, Secret — und gut auf Deutsch.
**Kein Organisations-Label**, also Ergänzung zu Dictionary/spaCy, kein Ersatz für
Firmennamen.

- **Leichtgewichtige ONNX-Route:** `onnxruntime` + `tokenizers` + `huggingface_hub`
  (kein torch). `PrivacyFilterDetector.load(variant="q4f16")` lädt die quantisierten
  Gewichte (~0,8 GB) einmalig vom HF-Hub (egress, siehe `network-allowlist.md`).
- **Injizierbar:** Konstruktor nimmt ein `predict`-Callable
  (`text -> [(BIOES-Label, start, end)]`); das Decoding (`_privacy_spans`) ist
  rein und offline testbar.
- gleiche `PRIORITY_MODEL`-Stufe und Struktur-/Stoppwort-Filter wie spaCy.

### Konfiguration (opt-in, Default aus)
```yaml
# config/known_entities.yaml
models:
  spacy:                              # Firmen/Orte (hat ORG-Label)
    enabled: true
    model: de_core_news_lg
    labels: [PERSON, COMPANY, LOCATION]
    min_length: 2
  privacy_filter:                     # Personen-/Kontakt-PII (kein ORG)
    enabled: true
    variant: q4f16                    # q4f16 (~0,8 GB) | q4 | quantized | fp16
    labels: [PERSON, ADDRESS, EMAIL, PHONE, ACCOUNT_NUMBER]   # optional
```
Beide Modell-Layer sind unabhängig zuschaltbar und ergänzen sich (spaCy für
Organisationen, privacy-filter für saubere Personen-/Kontakt-PII). Ohne
`models`-Abschnitt bleibt die Engine wie bisher (nur Dictionary + Regex).
Benötigt: `pip install onnxruntime tokenizers huggingface_hub` (privacy-filter)
bzw. `pip install spacy` + Modell (spaCy) — beide optional.

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
