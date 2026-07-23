# OpenCalc Studio — Architecture & Calculator Engine Contract

This document defines the component architecture for OpenCalc Studio (a premium,
accessible, offline-capable web calculator built with React + TypeScript strict +
Vite, shipped as a PWA) and the contract for the calculation engine. It is the
canonical reference for task assignment and integration order. Application UI
source is intentionally out of scope here; only the engine modules and their
public surfaces are specified.

---

## 1. High-Level Component Map

```
OpenCalc Studio
├── src/calculator/          # Pure, framework-agnostic engine (no DOM, no React)
│   ├── types.ts             # Shared types: Token, Node, EvalContext, DecimalType, errors
│   ├── decimal.ts           # Decimal shim + precision configuration (config-driven)
│   ├── tokenizer.ts         # tokenize(input): Token[]
│   ├── parser.ts            # parse(tokens): Node  (Pratt / recursive descent)
│   ├── evaluator.ts         # evaluate(node, ctx): Decimal
│   └── scientific.ts        # Scientific functions + DEG/RAD conversions
├── src/components/          # React UI (presentational + container)
│   ├── Keypad/              # Accessible keypad widgets
│   ├── Display/             # Expression + result display (live region)
│   ├── History/             # Scrollable, keyboard-navigable history list
│   ├── Settings/            # Angle mode, precision, theme, privacy toggles
│   └── Shell/               # Responsive layout, focus management, modals
├── src/state/               # Zustand store; engine is wrapped by a thin adapter
├── src/pwa/                 # Service worker, manifest, offline caching strategy
├── tests/                   # Vitest unit + integration tests
└── docs/                    # This directory
```

### Architectural principles

- **Engine/UI separation.** The engine under `src/calculator/` is a pure module
  with zero React or DOM dependencies. It must be consumable from tests, Web
  Workers, and the UI adapter without bundling UI code.
- **Deterministic core.** All numeric behavior is deterministic and independent
  of session, locale, or clock. Locale and display preferences live only in the
  format layer.
- **Fail-closed errors.** The engine never returns a silent fallback for an
  invalid input; it throws a typed error, and the UI adapter is responsible for
  surfacing a localized message.
- **No global mutable state.** Configuration (angle mode, precision) is passed
  through `EvalContext`, never read from a singleton.

---

## 2. Calculator Engine Contract

### 2.1 Modules under `src/calculator/`

| File         | Responsibility                                                        |
| ------------ | --------------------------------------------------------------------- |
| `types.ts`    | Shared types and typed error classes. No logic.                        |
| `decimal.ts`  | Decimal shim selection, precision config, rounding helpers.           |
| `tokenizer.ts`| Convert raw input string into a token stream.                          |
| `parser.ts`   | Convert tokens into an evaluation AST/Node.                            |
| `evaluator.ts`| Walk the AST and produce a `Decimal` result.                           |
| `scientific.ts`| Scientific functions: trig, log/exp, factorial, powers/roots; DEG/RAD. |

### 2.2 Public functions

The engine exposes these pure functions (barrel from `src/calculator/index.ts`):

```ts
// src/calculator/types.ts (excerpt — full contract below)
export interface EvalContext {
  angleMode: 'DEG' | 'RAD';
  precision: number;          // significant digits for rounding
  maxNodeDepth: number;       // guard against pathological / deep input
}

export function tokenize(input: string): Token[];
export function parse(tokens: Token[]): Node;
export function evaluate(node: Node, ctx: EvalContext): Decimal;
export function format(value: Decimal, opts: FormatOptions): string;

export interface FormatOptions {
  precision: number;
  notation: 'auto' | 'fixed' | 'scientific';
  groupSeparator?: string;    // '' by default; UI may set for locale display
  decimalSeparator: '.' | ','; // '.' internal; ',' only at the format boundary
}
```

- `tokenize` MUST be total: it returns a token array or throws `SyntaxError` /
  `MismatchedParens` for untokenizable input. It MUST NOT reach into `parse`.
- `parse` MUST produce a valid `Node` tree or throw. It enforces grammar and
  arity, including balanced parentheses and valid factorial operands.
- `evaluate` MUST be pure and total over well-formed nodes; runtime math
  failures raise typed errors (`DivisionByZero`, `DomainError`, `Overflow`).
- `format` is the ONLY place locale/grouping may be applied. The internal
  `Decimal` representation stays canonical (dot decimal).

### 2.3 Token & Node shapes (types.ts)

```ts
export type TokenKind =
  | 'number' | 'operator' | 'lparen' | 'rparen'
  | 'comma' | 'ident' | 'constant' | 'eof';

export interface Token { kind: TokenKind; value: string; pos: number; }

export type NodeKind =
  | 'num' | 'binop' | 'unary' | 'call' | 'constant' | 'factorial';

export interface NumNode      { kind: 'num'; value: Decimal; }
export interface BinopNode     { kind: 'binop'; op: string; left: Node; right: Node; }
export interface UnaryNode     { kind: 'unary'; op: string; operand: Node; }
export interface CallNode     { kind: 'call'; name: string; args: Node[]; }
export interface ConstantNode  { kind: 'constant'; name: string; }
export interface FactorialNode { kind: 'factorial'; operand: Node; }
export type Node =
  | NumNode | BinopNode | UnaryNode | CallNode | ConstantNode | FactorialNode;
```

### 2.4 Typed error kinds (all extend `CalcError`, carrying `code` + `message`)

| Error kind            | Raised by                  | Trigger example                                  |
| --------------------- | -------------------------- | ------------------------------------------------ |
| `DivisionByZero`       | evaluator                  | `1/0`, modulo by 0, `tan(90°)` (when relevant)   |
| `DomainError`          | evaluator / scientific      | `sqrt(-1)`, `log(-5)`, `asin(2)`, negative base**fractional exp** |
| `Overflow`             | evaluator / scientific      | `10^9999`, factorial of a very large integer      |
| `SyntaxError`          | tokenizer / parser          | malformed number, dangling operator, unknown ident|
| `InvalidFactorial`      | scientific                 | `0.5!`, negative integer `(-3)!`, non-integer arg |
| `MismatchedParens`      | parser                     | unbalanced `(` or `)`                             |

```ts
export abstract class CalcError extends Error {
  abstract readonly code:
    | 'DivisionByZero' | 'DomainError' | 'Overflow'
    | 'SyntaxError'    | 'InvalidFactorial' | 'MismatchedParens';
  pos?: number;
}
```

### 2.5 DEG / RAD handling

- Angle mode is conveyed exclusively via `ctx.angleMode` (`'DEG' | 'RAD'`).
- `scientific.ts` interprets angle arguments according to `ctx.angleMode` and
  normalizes to radians internally for all trig math. Trig inverse results are
  converted back to the active mode before returning.
- Affected functions: `sin`, `cos`, `tan`, `asin`, `acos`, `atan` (and any
  derived helpers). Hyperbolic functions are dimensionless and ignore angle mode.
- The UI adapter MUST reset `angleMode` from the Settings store on every
  evaluation; the engine MUST NOT cache angle mode.

### 2.6 Decimal strategy

- `decimal.ts` provides a single `Decimal` interface plus a config-driven shim,
  so the backing implementation can be swapped (e.g. a BigInt-rational fallback
  for offline SAM-scale builds) without touching callers.
- Floating-point `number` MUST NOT be used for final results; it is permitted
  only transiently inside a shim that immediately promotes to `Decimal`.
- Precision honors `ctx.precision` for rounding on `format` only;
  intermediate calculations keep full available precision to avoid premature
  rounding error.

---

## 3. UI Component Responsibilities (engine boundaries only)

| Component     | Engine interaction                                                                 |
| ------------- | ---------------------------------------------------------------------------------- |
| `Display`     | Calls `tokenize` for live tokenization previews; renders `format(result, opts)`.   |
| Result path   | `tokenize → parse → evaluate(_, ctx) → format(_, opts)`. Wrapped by the state adapter. |
| Error path    | The adapter catches `CalcError`, maps `code` -> localized message, pushes to an `aria-live` region. |
| `History`     | Stores expression + canonical result + `ctx` snapshot; replayable offline.          |
| `Settings`    | Owns `angleMode`, `precision`, theme; writes into the store consumed by the adapter. |
| `PWA`         | No engine interaction; ensures the engine bundle is cached offline.                |

---

## 4. Integration Order

The build must proceed bottom-up so each layer has stable contracts beneath it
before dependents are written. Phases map directly to task IDs in
`openagent-task-graph.json`.

1. **Phase 0 — Engine core (calc-task-001).**
   Implement `types.ts`, `decimal.ts`, `tokenizer.ts`, `parser.ts`,
   `evaluator.ts`. No scientific functions yet; ship the four typed-syntax/error
   paths (`DivisionByZero`, `DivisionByZero`, `Overflow`, `SyntaxError`,
   `MismatchedParens`). Unit-test the pipeline `tokenize → parse → evaluate`.

2. **Phase 1 — Scientific + DEG/RAD (calc-task-002).**
   Implement `scientific.ts` plus `InvalidFactorial` and `DomainError`. Add
   factorial validation and angle-mode normalization. Depends on Phase 0.

3. **Phase 2 — Standard UI (calc-task-003).**
   Build `Keypad`, `Display`, `Shell`, the state adapter, and the
   `CalcError` -> message mapping with accessible error surfacing. Depends on
   Phase 0 (uses core engine functions and basic errors).

4. **Phase 3 — History + Settings + PWA (calc-task-004).**
   Wire `History` (replayable), `Settings` (angle mode / precision / theme /
   privacy), and `pwa/` (manifest, service worker, offline cache of the engine
   bundle). Depends on Phases 1 and 2 (uses scientific functions, angle-mode UI).

5. **Phase 4 — QA tests (calc-task-005).**
   Vitest unit tests for the engine pipeline, angle-mode parity, error matrix,
   and a component-level RTL suite for UI / accessibility. Depends on Phases 1–3.

6. **Phase 5 — Security review (calc-task-006).**
   Threat-model the engine (input limits, `maxNodeDepth`, decimal-stack
   overflow, no `eval`), PWA caching scope, and credential/telemetry-free
   offline guarantees. Depends on Phase 4.

7. **Phase 6 — Docs (calc-task-007).**
   User guide, keyboard reference, error-message reference, accessibility notes,
   and contribution/engine-extension guide. Depends on Phases 1–3.

8. **Phase 7 — Integration review (calc-task-008).**
   End-to-end acceptance matrix walkthrough, cross-phase contract verification,
   and sign-off against `acceptance-criteria.md`. Depends on Phases 1–6.

9. **Phase 8 — Release hardening (calc-task-009).**
   Strict-mode + `tsc --noEmit` cleanliness, bundle-size budget, Lighthouse /
   a11y audit re-run against the acceptance matrix, and changelog/release
   notes. Final gate. Depends on Phase 7.

---

## 5. Cross-cutting invariants (enforced in review)

- No `eval`, no `Function` constructor, no dynamic `import` of user input.
- Every public engine function is pure; none reads browser globals.
- Every `CalcError` has a stable `code` string used as the i18n key.
- `tokenize -> parse -> evaluate -> format` is the only sanctioned execution
  pipeline; shortcuts that skip `parse` are forbidden.
- Angle mode and precision flow only through `EvalContext`; no hidden globals.

---

## 6. Interfaces between agents

| Producing agent   | Consuming agent   | Artifact                                                                 |
| ----------------- | ------------------ | ------------------------------------------------------------------------ |
| agy-frontend (engine) | agy-frontend (UI)  | `src/calculator/index.ts` public exports + `CalcError.code` set          |
| agy-frontend      | agy-qa             | Vitest harness + example fixtures                                        |
| agy-frontend      | agy-security       | Engine surface, PWA scope, dependency manifest                           |
| agy-frontend      | agy-docs           | Public function signatures, error codes, keyboard bindings               |
| agy-qa            | agy-security        | Failing/marginal test matrix for risk areas                              |
| All               | GLM Orchestrator   | Final acceptance-matrix walkthrough (calc-task-008)                      |
