"""fsx — on-premise financial-statement extraction & anonymisation pipeline.

This package is the backbone the rest of the pipeline builds on:

* :mod:`fsx.schemas`   — the three data levels (raw extraction, normalised
  facts, analysis features) that every stage reads from / writes to.
* :mod:`fsx.anonymize` — the local anonymisation engine: pluggable detectors
  (regex, dictionary, …), span merging, and consistent pseudonym replacement.
* :mod:`fsx.config`    — loading the project-specific known-entities YAML.

Parsing adapters (PyMuPDF / pdfplumber / Camelot / OCRmyPDF / Docling) and the
later detector layers (spaCy / Presidio / OpenAI Privacy Filter) plug into this
backbone; they are deliberately not required for the core to work or be tested.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
