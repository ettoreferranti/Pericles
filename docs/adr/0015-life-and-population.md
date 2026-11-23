# ADR-0015: Life and population

- **Status:** Accepted
- **Date:** 2026-11-23
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

M1c gives villagers a life cycle (REQ-SIM-003 AC2, REQ-SIM-012, -015, -016, -017, REQ-SIM-018 AC1): needs, health, death, couples, births, children, coming of age and inheritance. The spec (§4.3, §4.4) names these mechanics without fixing their rules. The user requires every parameter to be tweakable from a settings file (2026-11-23).

## Decision

1. **Needs are content.**
   - A need's level runs from 0 (satisfied) to its `critical` value.
   - Each tick, a need rises by its `rate` × hours per tick, then is clamped to 0…critical. The `rate` is resolved through the modifier system: target kind `need`, the need's id, attribute `rate`, base `rate_per_hour`. The current season's modifiers and the villager's trait modifiers take part.
   - A need's `relief` says what lowers it:
     - `eat`: eating an item lowers the need by the item's `nutrition` × quantity.
     - `sleep`: while sleeping, the need falls by `sleep_relief_per_hour` (× `home_sleep_multiplier` at home) instead of rising.
     - `shelter`: at home, the need falls by `shelter_relief_per_hour` instead of rising.
2. **Health** is `max_health − damage`.
   - Each need at its critical value adds `damage_per_hour` × hours per tick to the damage. With no need at critical, damage heals at `health_regen_per_hour`.
   - When the damage reaches `max_health` the villager dies. The cause is the `death_cause` of the first damaging critical need in id order.
   - A need that does damage must name a death cause (registry rule).
3. **Eating and sleeping.**
   - Eating is an instant intent (`Eat`). It destroys the food, and its `ate` event carries a `destroyed` bundle.
   - Sleeping is an activity of kind `sleep`. It ends by itself when every `sleep` need reaches 0 (event `woke`), or through the usual interruption.
4. **Homes.**
   - A villager's `home` is a completed building with `housing > 0`. It must be owned by the villager or their partner (communal counts), and have fewer residents than its housing.
   - "At home" means within reach of the home (ADR-0014 §6).
5. **Age.**
   - Age is counted in days from `born_tick`.
   - Adulthood is a flag: false at birth, and set by coming of age. Villagers created by an experiment are adults unless the experiment says otherwise.
   - Past `old_age_days`, the daily death probability is `min(1, old_age_death_chance × old_age_death_growth^(days past old_age_days))`.
6. **Couples need mutual consent.**
   - `ProposeCouple` records a proposal that lapses after `couple_proposal_ttl_ticks`. A matching `AcceptCouple` from the proposed villager forms the couple. M3 dialogue will issue these intents.
   - Couples last until a death.
   - Any two unpartnered adults may couple. Conception needs one partner of `bearing_sex` and one of another sex.
7. **Conception and birth.**
   - Once per day, each bearing adult with a living partner may conceive if all of these hold:
     - they share a completed home with free capacity, counting pregnancies due in that home;
     - the village food stock (the total nutrition held in inventories and stores) is at least `birth_food_per_capita` × population;
     - at least `birth_interval_days` have passed since their last birth;
     - a draw against `conception_chance_per_day` succeeds.

     Otherwise pregnancy does not start.
   - The child is born `gestation_days` later at the mother's position. Its home is the mother's, and its sex is drawn from `sexes`.
8. **Children** may only use the intents in `child_intents`. They may only start actions that carry a tag from `child_action_tags`. Anything else is rejected with `too_young`. Scripted child behaviour comes with the scripted AI (REQ-AGT-008, plan M1d).
9. **Coming of age** happens at the first day boundary after `adult_age_days`.
   - The model follows `model_rule`:
     - `inherit`: a parent's model, living or dead, chosen with the state RNG, falling back to `adult_model`;
     - `fixed`: `adult_model`.
   - The new adult's memories are the notable events they witnessed as a child, up to `childhood_memory_limit`, most recent kept. These are:
     - events of a `family_events` kind that name the child, a parent or a sibling;
     - every event of a `village_events` kind.
10. **Death and inheritance** go through one function, `lifecycle.die`, which god powers (raid, epidemic) will also call. It does these things in order:
    1. It interrupts work, so reserved inputs return to the estate.
    2. It ends a pregnancy and unlinks the partner.
    3. It drops the dead villager's proposals and moves them to `WorldState.dead`.
    4. It distributes the estate. Each item goes to the heirs in order (partner, then children, oldest first) as far as their carry limit allows. What is left goes to completed communal stores in id order, as far as their capacity allows. Any remainder is destroyed, recorded by `estate_lost` with a `destroyed` bundle.
    5. It reassigns buildings:
       - a personal building goes to the first heir, or becomes communal if there are no heirs;
       - a shared building drops the dead owner and adds the first heir if absent, then collapses to personal or communal as the owner count requires.
11. **No magic values.**
    - Engine parameters are `EngineConfig` fields, and the `engine:` section of a YAML settings file sets them (`pericles.experiment.settings`). The playable defaults live in the packaged `default_settings.yaml`, which lists every field.
    - Game values are content.
    - Core code contains no other numeric literals except 0, 1 and an allowlist of definitional constants, enforced by a test.
12. **Tick order:**
    1. intents
    2. work (sleep excluded)
    3. movement
    4. needs and health
    5. due births
    6. proposal expiry
    7. at a day boundary: regrowth, old-age deaths, coming of age, conception
    8. witnessing
    9. modifier expiry
    10. tick + 1

## Consequences

+ Every life rule is parameterised and testable through intents and the clock.
+ Death, births and inheritance keep the item ledger exact.
− Estates can lose items when heirs and stores are full. This is recorded, not hidden.
− Children's behaviour is inert until the scripted AI exists (M1d).
