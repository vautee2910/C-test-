# Netzwerk-Allowlist (Egress)

Diese Pipeline ist auf **On-Premise-Betrieb** ausgelegt: Bei der eigentlichen
Verarbeitung (Inferenz) verlassen **keine** Mandantendaten den Rechner. Egress
wird nur für **einmalige Setup-/Download-Schritte** benötigt — danach laufen alle
Detektoren offline aus dem lokalen Modell-Cache.

Die Allowlist wird beim Anlegen der Ausführungsumgebung gesetzt
(siehe https://code.claude.com/docs/en/claude-code-on-the-web). Domains unten
sind als Hostnamen zu hinterlegen.

---

## Stufe 1 — Parsing-Adapter (PyMuPDF)
Kein Egress zur Laufzeit. Nur einmalig zur Installation:

| Zweck | Domains |
| --- | --- |
| Pip-Pakete (PyMuPDF, pdfplumber, …) | `pypi.org`, `files.pythonhosted.org` |

---

## Stufe 2 — Modellbasierte Detektoren (spaCy / Presidio / Privacy-Filter)

Diese Schicht ergänzt Regex + Dictionary um statistische NER. Egress wird
**ausschließlich für das einmalige Herunterladen der Modelle** benötigt. Nach dem
Caching (z. B. `~/.cache/huggingface`, spaCy-Paket im venv) ist **kein**
Netzwerkzugriff mehr nötig — Inferenz ist vollständig lokal.

| Zweck | Domains |
| --- | --- |
| Pip-Pakete (`spacy`, `presidio-analyzer`, `transformers`, …) | `pypi.org`, `files.pythonhosted.org` |
| spaCy-DE-Modell (`de_core_news_lg`/`_sm`, ausgeliefert als GitHub-Release-Wheel) | `github.com`, `codeload.github.com`, `objects.githubusercontent.com`, `raw.githubusercontent.com` |
| HuggingFace-Modellgewichte (Transformer-NER / Privacy-Filter-Modell) | `huggingface.co`, `hf.co`, `cdn-lfs.huggingface.co`, `cdn-lfs-us-1.huggingface.co` |
| HF Xet-Storage-Backend (neuer LFS-Nachfolger) | `*.xethub.hf.co` (insb. `cas-bridge.xethub.hf.co`) |

**Minimaler Satz** (wenn nur Regex+Dictionary+spaCy, ohne HF-Transformer):
`pypi.org`, `files.pythonhosted.org`, `github.com`, `codeload.github.com`,
`objects.githubusercontent.com`, `raw.githubusercontent.com`.

**Mit HF-Transformer-Modell** zusätzlich:
`huggingface.co`, `hf.co`, `cdn-lfs.huggingface.co`,
`cdn-lfs-us-1.huggingface.co`, `*.xethub.hf.co`.

> ⚠️ **Hinweis „OpenAI Privacy Filter":** Falls damit ein *lokales* Modell
> gemeint ist (HF-gehostet), gilt die HF-Allowlist oben — die Daten bleiben
> lokal. Falls damit eine *gehostete OpenAI-API* gemeint wäre, würde das
> Mandantendaten nach außen geben und dem On-Prem-Ziel der Anonymisierung
> widersprechen. Für die Anonymisierungs-Schicht daher ein **lokales** Modell
> verwenden, keine externe API.

---

## Empfohlenes Vorgehen
1. Modelle **einmalig** in einer Umgebung mit der obigen Allowlist herunterladen
   und cachen (oder vorab in das Image/Volume legen).
2. Für den **produktiven Verarbeitungslauf** die Egress-Policy auf *kein
   Netzwerk* (bzw. nur das interne OpenWebUI-Gateway) stellen — Stufe 1 und 2
   laufen dann garantiert offline.
3. Externer LLM-Zugriff (OpenWebUI-Gateway) ist eine **separate** Egress-Frage
   und erst nach dem Export-Guard relevant; nur **anonymisierter** Text geht dort
   hinaus.
