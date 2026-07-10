"""Web-grounded answer generation (Gemini "Grounding with Google Search").

ToS-clean by design (a hard project policy): answers are produced through
Gemini's official Google Search grounding tool, never by scraping search
results ourselves. See ``answer.py`` for the guarded generation path.
"""

from __future__ import annotations
