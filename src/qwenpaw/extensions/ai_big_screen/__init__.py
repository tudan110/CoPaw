# -*- coding: utf-8 -*-
"""AI big-screen generation pipeline (P2 redesign).

Three decoupled layers replacing the legacy monolith in
``extensions/api/ai_big_screen_service.py``:

- L1 ``intent``         natural language -> typed ``ScreenPlan``
- L2 ``capabilities``   descriptor registry -> honest ``CapabilityResult``
- L3 ``orchestration``  plan + data -> sanitized screen components

``pipeline`` wires the layers together; ``patch`` reuses them for
incremental edits. See docs/solution-design/ai-big-screen-redesign-spec.md.
"""
