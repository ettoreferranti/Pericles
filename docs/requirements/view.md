# VIEW: Viewer

### REQ-VIEW-001: WebSocket protocol
Must · M5 · Accepted
- AC1: The server exposes a versioned WebSocket protocol for state snapshots, event streams, control commands and interventions.
- AC2: Protocol messages are defined by a schema shared by server and viewer, and contract-tested on both sides.

### REQ-VIEW-002: 3D map rendering
Must · M5 · Accepted
- AC1: The viewer renders terrain, resource nodes, buildings and villagers in simple low-poly 3D, with orbit, zoom and pan.
- AC2: Villagers can be colour-coded by model group (toggle).
- AC3: Holds ≥ 30 fps with 150 villagers on a 128×128 map on the target machine.

### REQ-VIEW-003: Live mode
Must · M5 · Accepted
- AC1: Attaches to a running simulation, with pause, single-step, speed control and a wait-for-LLM toggle.

### REQ-VIEW-004: Replay mode
Must · M5 · Accepted
- AC1: Opens a run directory. A timeline scrubber seeks to any tick by loading the nearest snapshot and applying events.
- AC2: The state reconstructed at tick T equals the engine's state at tick T (hash comparison in tests).

### REQ-VIEW-005: Villager inspector
Must · M5 · Accepted
- AC1: Selecting a villager shows needs, inventory, plan, goals, memories, opinions, model, and recent prompts and raw responses.

### REQ-VIEW-006: Social panels
Should · M5 · Accepted
- AC1: Panels show the town-square board, meeting transcripts with votes, and dialogue transcripts, each linked to the villagers involved.

### REQ-VIEW-007: Control panel
Must · M5 · Accepted
- AC1: In live mode, the experimenter can edit parameters, add, amend or repeal laws (with an optional hook), and trigger god powers. Each action is sent as an intervention.

### REQ-VIEW-008: Dashboards
Should · M5 · Accepted
- AC1: Live mini-charts of population, food stock, Gini, violations and LLM failure rate.
