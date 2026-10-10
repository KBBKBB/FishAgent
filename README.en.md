# FishAgent

> An AI agent for anglers: **fish-activity analysis** and **fishing-spot recommendation**.
> Owner: KBB OPC ｜ Positioning: a **decision-support tool** (advisory only, no catch guarantee).

## Problem

1. **"Is today good for fishing?"** — fish activity depends on pressure, temperature, wind and rain, which ordinary users cannot read from raw weather data.
2. **"Where should I go?"** — even when willing to go, users lack a way to judge nearby waters and spots.

**Core gap**: data is everywhere, but nobody makes the **"whether / where / when"** decision for the user.

Differentiation (see `Spec/Mission.md`): decision-first (not data-first), merge "reachable" and "worth it",
explainability, and the courage to **advise against** a trip.

## Current stage: M1 research

> **M1 writes no product code — it only validates assumptions.** The output is a go/no-go answer.

Done and reproducible in this repo:

- ✅ **Runnable prototype** `prototype/`: coordinate conversion + dual-path water POI recall + drive-time estimation + fish-activity rules
- ✅ **Tiling strategy** to bypass Amap's 50 km `radius` cap
- ✅ **Weather source verification** with Open-Meteo
- ✅ **Competitor evidence**: vertical apps already ship "pressure + AI bite forecast + golden hours"

```bash
cd prototype
python3 demo.py --mock      # offline demo, no API key needed
python3 -m pytest -q        # 21 unit tests
```

Pending (external): Amap key measurements (A1–A4), Mini-Program location permission (A7), legal review, manual competitor review.

## Docs

```
项目立项文档.md          # Full project charter (Chinese)
Spec/Mission.md           # Why / what / what-not (principles P1–P7)
Spec/TechStack.md         # How (stack + hard constraints R1–R8)
Spec/Roadmap.md           # When / how far / when to stop (M1–M5 + gates)
Spec/M1/                  # M1 research deliverables
prototype/                # M1 prototype (dependency-free Python)
```

> **Single source of truth** for thresholds: chapters 8–9 of `项目立项文档.md`.

## Hard constraints (non-negotiable)

| ID | Constraint |
|---|---|
| R1 | One coordinate entry point: WGS84 → GCJ-02; never pass raw coordinates to map APIs |
| R2 | Hard-validate `radius` ≤ 50000 m (over-limit silently degrades to 3000 m) |
| R3 | Never ship the Amap key to clients (server-side proxy + IP allowlist + `sig`) |
| R4 | Drive time: use `entr_location`; compute outbound + return separately ≤ 7200 s |
| R5 | Ban-zone filtering before returning results |
| R6–R8 | AI content labeling / location privacy / never rebroadcast weather forecasts |

## Contributing

1. Fork the repository
2. Create a `Feat_xxx` branch
3. Commit your changes (run `prototype` tests first)
4. Open a Pull Request

See `Spec/Roadmap.md` for task IDs and deliverables.
