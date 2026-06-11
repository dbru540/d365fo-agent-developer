# Graphify Coverage Plan

## Goal

Use `graphify` as the main graph knowledge layer over the D365 corpus, in multiple manageable waves, while keeping `d365fo_agent` as the deterministic generation and merge engine.

## Why Waves

`PackagesLocalDirectory` is too large for a single practical graphification run.

Observed scale:

- `ApplicationSuite`: ~279k files
- `ApplicationFoundation`: ~30k files
- `ApplicationPlatform`: ~24k files
- `Retail`: ~20k files

Running `graphify` on the full corpus in one shot would be slow, operationally fragile, and hard to interpret.

## Coverage Strategy

### Wave 1: Custom Business Packages

Primary purpose:

- maximize value for `spec -> code`
- capture actual custom patterns first

Target packages:

- `BABAccountsPayable`
- `BABGeneralLedger`
- `BABAccountsReceivable`
- other `BAB*`, `Fiveforty*`, `FLexmind*`, and known custom packages

### Wave 2: Core Standard Dependencies

Primary purpose:

- enrich standard references that custom packages rely on

Target packages:

- `ApplicationFoundation`
- `ApplicationPlatform`
- `ApplicationCommon`

### Wave 3: Large Functional Standard Surface

Primary purpose:

- expand retrieval for common app behaviors and reference implementations

Target packages:

- `ApplicationSuite`
- selected large business domains used by the custom packages

### Wave 4: Remaining Standard / Specialized Domains

Primary purpose:

- complete graph coverage
- cover verticals and edge cases

Target packages:

- remaining packages in `PackagesLocalDirectory`

## Operating Rules

- Prefer per-package or small grouped-package runs over one massive run.
- Keep `graphify` outputs next to each package unless a later consolidation step is introduced.
- Use `--no-viz` for batch waves first; add heavier visualization later only where useful.
- After each wave, inspect graph outputs before deciding the next grouping.

## Integration With `d365fo_agent`

`graphify` is the graph knowledge layer.

`d365fo_agent` remains responsible for:

- spec parsing
- artifact planning
- deterministic XML generation
- merge mode for existing artifacts

The next integration step after graphifying more packages is to read `graphify` outputs and use them to improve:

- example selection
- dependency-aware artifact planning
- object relationship discovery across packages

## First Recommended Execution

Start with:

- `BABAccountsPayable`
- `BABGeneralLedger`

These are high-value custom packages and small enough to run before the larger standard waves.

