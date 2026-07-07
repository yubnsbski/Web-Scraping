"""Brainstem: the fixed pipeline every chat turn passes through.

See ``docs/brainstem.md`` (section 2) for the governing design. This package
is the extraction target of Sprint B0: a pure refactor of the logic that
previously lived directly in :mod:`investment_assistant.webapi.chat`, split
into named stages (ingest -> context -> retrieve -> route -> generate ->
comply -> assemble) so later sprints (N0/N1/O1/O2/O3) have seams to plug
into without another rewrite of the webapi layer.

``chat.turn.v1`` response shape and behavior are unchanged by this package;
:mod:`investment_assistant.webapi.chat` now delegates to
:mod:`investment_assistant.brainstem.webapi_adapter`.
"""

from __future__ import annotations
