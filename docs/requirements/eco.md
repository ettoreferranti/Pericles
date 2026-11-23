# ECO: Economy

### REQ-ECO-001: Ownership
Must · M1 · Implemented
- AC1: Every building and store has an ownership of `personal(owner)`, `shared(owners)` or `communal`.
- AC2: Taking items from a store the villager does not own emits a `take_unowned` event, with item, quantity, store and owner.

### REQ-ECO-002: Barter trade
Must · M3 · Accepted
- AC1: A trade is an atomic exchange of two item bundles between two villagers who both accepted the same terms.
- AC2: The trade fails, with nothing transferred, if either party lacks the goods at execution time.
- AC3: Every executed trade emits an event with the implied exchange rates.

### REQ-ECO-003: Coins and Mint
Must · M3 · Accepted
- AC1: Coins are an ordinary item produced only by the minting recipe at a Mint, from gold ore.
- AC2: Coins can be part of any trade bundle.
- AC3: Whether a Mint exists at the start, and which villagers know minting, are experiment parameters.

### REQ-ECO-004: Gifts and lending
Should · M3 · Accepted
- AC1: A villager can give items without anything in return (a gift event).
- AC2: A loan is recorded as a promise with terms and a due tick (see REQ-SOC-002).

### REQ-ECO-005: Price observation
Should · M4 · Accepted
- AC1: The analysis can compute the implied price of every item in coins and in a reference good, per in-game day, from trade events.
