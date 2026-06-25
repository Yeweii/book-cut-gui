# Design: v2.4 Manual Split Line

## Context

The `book_cut` tool splits two-page book scans into single pages. It has 3 auto split
strategies (`half` / `gutter` / `border`) plus `none` (skip). Auto strategies fail
on:

- Severely smudged scans (gutter can't find continuous white)
- Tilted + blurry scans (border Hough can't find 版框, half drifts > 20%)
- Irregular hand-copied / facsimile pages (版心 inconstant)

Today users work around by hand-measuring in Photoshop and writing `--half-offset N` to a script.
There's a `ManualCropProfile` for **post-split padding** (v2.2+) but no equivalent for
**choosing the split line itself**.

The user wants:
1. GUI flow: open a Toplevel showing the first page (or first PDF page rendered), let user
   draw a single vertical line, persist the x as a per-book profile.
2. CLI flow: a subcommand `--pick-split-line -i book.pdf -o preset.json` reuses the same
   Toplevel, writes the JSON, so scripts can run non-interactively afterwards with
   `--split manual --manual-split-preset preset.json`.

The change is additive: zero impact on existing `--split` values, and `--split manual`
is orthogonal to `--crop manual` (they can be used together).

---

## Goals

- Provide `--split manual` that uses a user-supplied x to slice the page
- Provide a `SplitLinePicker` Toplevel for interactive selection
- Provide a `--pick-split-line` subcommand that reuses the Toplevel and writes JSON
- Persist the choice as a `ManualSplitProfile` JSON preset (v1 schema, stable for v2.4+)
- Strict deskew-state consistency check to prevent silent coordinate drift
- Graceful handling of single-page detection, 1:3+ cross-page, source_size mismatch

## Non-Goals

- Per-page line override (out of scope; v2.5+ if needed)
- 1:3+ native support (out of scope; v2.4 emits a warning + best-effort slice)
- Multi-page preview switcher in picker (out of scope; trust first page or use `--dry-run`)
- Undo / redo (YAGNI for v1)
- Changing `--page-order` default (separate concern)
- Changing `--crop manual` semantics (orthogonal feature)

---

## Decisions

### D1. New module: `src/book_cut/split/manual.py`

**Decision**: Create a sibling to `split/half.py`, `split/gutter.py`, `split/border.py`.

```
src/book_cut/split/
  ├── __init__.py
  ├── half.py
  ├── gutter.py
  ├── border.py
  └── manual.py    ← NEW
```

**Rationale**: Existing split strategies are siblings. Putting manual there (vs.
in `detect/manual.py`) is correct because `detect/manual.py` is for **crop** (post-split
padding) — different concern. Using a sibling module avoids the naming trap.

**Consequence**: `from book_cut.split import ManualSplitProfile, apply_manual_split` works
cleanly. `book_cut/detect/manual.py` is untouched.

---

### D2. Per-book single line, not per-page

**Decision**: One `split_x` for the entire book. No per-page override in v2.4.

**Rationale**:
- 95%+ of scan books have consistent page geometry (same gutter position across all pages)
- v2.2 `ManualCropProfile` is also per-book — consistency
- Per-page override would 4× the JSON size and 3× the picker UI complexity
- v1.4 book-cut users have come to expect "one profile for the whole book"

**Migration path** (if needed later): extend `ManualSplitProfile` to `per_page_overrides: dict[int, int] | None = None`
without breaking v1 schema (default `None` = book-wide).

---

### D3. JSON v1 schema with strict version validation

**Decision**: Single v1 schema. `from_json` rejects unknown versions with `MS006`.

**Rationale**:
- v2.4 is the first release of this feature — no migration concern
- Strict validation prevents future silent corruption (e.g., v3 schema fields being ignored)
- If v2 lands (per-page override), `from_json` gets a new branch; v1 still works

**Schema** (v1):

```json
{
  "version": 1,
  "split_x": 450,
  "source_size": [920, 700],
  "page": 1,
  "deskew_applied": true,
  "notes": "尸子卷首页"
}
```

**Field rationale**:
- `version`: forward compat
- `split_x`: the only required computation field
- `source_size`: (W, H) at time of selection; MS003 warns on mismatch but doesn't fail
- `page`: 1-based page number used for selection (informational, for human re-picking)
- `deskew_applied`: critical for MS009 consistency check
- `notes`: free-form Chinese text support via `ensure_ascii=False`

---

### D4. `apply_manual_split` returns exactly 2 sub-arrays (no 1:3 support)

**Decision**: `apply_manual_split(arr, profile) -> list[np.ndarray]` always returns
exactly 2 elements. 1:3+ handling is the orchestrator's job, not the splitter's.

**Rationale**:
- Single Responsibility: the splitter does one cut at one x
- Simpler contract: 2 outputs always
- 1:3 detection is heuristic (`arr.shape[1] / 2 < profile.split_x`), lives in orchestrator
- Clean test: just test `[arr[:, :x], arr[:, x:]]`

**Consequence**: orchestrator wraps with MS010 logic if 1:3 is suspected.

---

### D5. deskew_applied consistency: strict (MS009 fatal)

**Decision**: If `args.deskew != profile.deskew_applied`, exit 1 with MS009.

**Rationale**:
- The split_x coordinate is meaningless across a deskew transformation
- A silent warn would lead to off-by-many-pixels splits, hard to debug
- The fix is one command: re-pick with `--deskew` enabled (or disable for run)
- Cheap to enforce: one bool check at pipeline start

**Trade-off**: users who toggle `--deskew` between pick and run will get an error.
This is intended friction.

---

### D6. Picker as a Toplevel, not a full-window app

**Decision**: `SplitLinePicker` is a `tk.Toplevel` rooted in the main GUI window, not
a separate process. For `--pick-split-line` CLI subcommand, it roots in a hidden root
`Tk()` that is destroyed after the picker closes.

**Rationale**:
- Consistent with v2.2 `CropCanvas` (sub-widget of main window)
- Reuses `tk.Tk()` lifecycle; no extra process management
- For CLI subcommand, the hidden root is a 3-line pattern; no extra dependency

**Consequence**: `--pick-split-line` requires a display (won't work over plain SSH
without X forwarding). This is consistent with `--gui` and is acceptable for v2.4.

---

### D7. Picker shows the first page only

**Decision**: Picker always shows page 1 (or the only page for image inputs). No
page switcher in v2.4.

**Rationale**:
- "First page" is the conventional representative page
- Per-book single line — first page is enough
- A switcher would add 50+ lines of UI code for marginal value
- If user suspects variance, `--dry-run` with the preset shows all pages' cut positions

**Workaround**: user can re-pick from a different page by editing the picker source
later (out of scope for v2.4).

---

### D8. Click-to-position + Spinbox + drag, all live-syncing

**Decision**: Three input methods on the same x value, all bound through a single
`Tkinter.IntVar`. The Canvas redraws on every change.

**Rationale**:
- Different users have different interaction preferences (mouse vs keyboard)
- Single source of truth (IntVar) prevents drift
- Standard Tkinter pattern; no third-party widget needed

**Implementation**:
- `self.x_var = tk.IntVar(value=initial_x or w // 2)`
- `tk.Spinbox(textvariable=self.x_var, from_=1, to=w-1)`
- Canvas binds `<Button-1>`, `<B1-Motion>`, `<MouseWheel>`, `<Key>`, `<Double-Button-1>`
- Spinbox `command=` and `validate=` update the Canvas

---

### D9. Single-page detection: skip manual, warn MS007

**Decision**: When `auto_single_page=True` and a page is detected as single-page, the
manual split step is skipped for that page and the whole arr passes to crop. A
`MS007` warning is logged.

**Rationale**:
- Manual split makes no sense on a single page (no gutter to draw)
- Silent skip would confuse users ("why didn't my x apply?")
- Warning is the right level: not fatal, but visible

**Consequence**: pages 1, 5, 9 may not be split if they happen to be cover pages.
The output page count may differ from a pure 1:2 split. Documented in CHANGELOG.

---

### D10. 1:3+ handling: warn + best-effort

**Decision**: Detect 1:3 with a simple heuristic: `arr.shape[1] / 2 < profile.split_x`
(i.e., the user picked a line in the left third of a wide image). If detected, emit
MS010 warning and use `split_x` for first cut, second cut at `split_x * 2` (assuming
symmetric tri-fold), tail as third.

**Rationale**:
- Better than crashing or silently producing 2-arrays for a 3-page image
- The heuristic is rough but matches the common case (symmetric 1:3)
- Documented limitation: v2.4 doesn't truly support 1:3; v2.5+ could add explicit
  `split_xs: list[int]` to `ManualSplitProfile`

**Consequence**: 1:3 with non-symmetric gutter positions will be wrong. Acceptable for v2.4.

---

## Architecture

```
CLI / GUI entry
    │
    ├── --pick-split-line  →  iter_pages →  deskew (if enabled)  →  SplitLinePicker  →  write JSON
    │                                                                                       │
    │                                                                                       ▼
    └── main run  →  pipeline  →  orchestrator._compute_page  →  apply_manual_split (manual case)
                                                          │
                                                          ├── auto_single_page? → MS007 warn + skip
                                                          ├── 1:3 heuristic?    → MS010 warn + best-effort
                                                          ├── deskew mismatch?  → MS009 fatal
                                                          └── normal            → arr[:, :x] | arr[:, x:]
```

### File-level change summary

| File | Change | LOC |
|------|--------|-----|
| `src/book_cut/split/manual.py` | NEW: `ManualSplitProfile`, `to_json`, `from_json`, `apply_manual_split` | ~150 |
| `src/book_cut/split/__init__.py` | Re-export `ManualSplitProfile`, `apply_manual_split` | ~5 |
| `src/book_cut/split/picker_ui.py` | NEW: `SplitLinePicker` Toplevel class | ~200 |
| `src/book_cut/pipeline/orchestrator.py` | Add `manual` branch in `_compute_page`; add `manual_split_profile` param | ~30 |
| `src/book_cut/cli.py` | Add 4 args: `--split manual` choice, `--manual-split-x`, `--manual-split-preset`, `--pick-split-line` | ~80 |
| `src/book_cut/gui.py` | Add `manual` to split combobox; add `选切分线...` button; `run_pick_split_line` entry | ~70 |
| `tests/test_manual_split.py` | NEW: 12 test cases | ~250 |
| `samples/crop_profiles/v2_manual_split_example.json` | NEW: example preset | ~10 |
| `README.md` | Update split table + usage | ~30 |
| `CHANGELOG.md` | Add 0.3.6 section | ~30 |
| `docs/sessions/2026-06-25-v2.4-manual-split-line.md` | NEW: session note | ~80 |

**Total**: ~940 lines new/changed.

---

## Risks & Trade-offs

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | deskew state mismatch → silent off-by-pixels split | High | MS009 strict fatal at pipeline start |
| R2 | Per-book assumption wrong for variable-layout books | Medium | Documented limitation; `--dry-run` validation workflow |
| R3 | CLI subcommand requires X display | Low | Consistent with `--gui`; v2.5+ could add `--pick-split-line --headless` for env-based picking |
| R4 | First-page-only picker may mislead on inconsistent books | Low | Document; recommend `--dry-run` verification |
| R5 | `auto_single_page` + manual split interaction confusing | Medium | MS007 warn explains behavior |
| R6 | Naming: `--split manual` vs `--crop manual` confused | Low | CLI `--help`; GUI uses full Chinese "手动（画线）" |
| R7 | 1:3+ heuristic wrong for non-symmetric | Medium | MS010 warn; v2.5+ native support |
| R8 | `source_size` mismatch warn can be ignored | Low | MS003 + CHANGELOG note |

---

## Test Plan

12 unit tests in `tests/test_manual_split.py` (TDD: red → green → refactor):

| # | Test | Validates |
|---|------|-----------|
| T1 | `to_json` → `from_json` round-trip preserves all fields | D3 |
| T2 | `from_json` rejects version != 1 with `MS006` | D3 |
| T3 | `from_json` rejects `split_x < 1` with `MS001` | D3 |
| T4 | `from_json` rejects `split_x >= source_size[0]` with `MS001` | D3 |
| T5 | `apply_manual_split` returns 2 sub-arrays of correct shapes | D4 |
| T6 | `apply_manual_split` warns (MS003) on `source_size` mismatch | D4 |
| T7 | `apply_manual_split` raises on width < 2 | D4 |
| T8 | CLI argparse accepts `--split manual` | CLI |
| T9 | CLI rejects `--split manual` without x or preset with `MS004` | CLI |
| T10 | orchestrator `_compute_page` with `split_strategy="manual"` and valid profile | D-pipeline |
| T11 | orchestrator with `args.deskew=True` and `profile.deskew_applied=False` exits with `MS009` | D5 |
| T12 | orchestrator with `auto_single_page=True` + detected single page + `split_strategy="manual"` warns MS007 | D9 |

Plus 3 integration tests (real sample PDF + JSON preset round-trip).

---

## Migration / Compatibility

- **Zero backward-incompatible change**: existing `--split` values unchanged
- **JSON preset**: new file, no existing user has one
- **CLI flags**: all new, all optional with `default=None`
- **GUI**: new combobox item, new button (hidden by default until "manual" selected)
- **Sample files**: new `v2_manual_split_example.json` added to `samples/crop_profiles/`
- **Old docs**: README updated; old content preserved

No data migration. No version flag needed.
