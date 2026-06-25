# Spec: v2.4 Manual Split Line

## ADDED Requirements

### Requirement: `ManualSplitProfile` dataclass

The system MUST provide a `ManualSplitProfile` dataclass in `src/book_cut/split/manual.py`
representing a user-selected vertical split line, applicable to the entire book.

```python
@dataclass(frozen=True)
class ManualSplitProfile:
    split_x: int                       # post-deskew 坐标系下的中缝 x（≥1, < W）
    source_size: tuple[int, int] | None = None  # (W, H)，跨书校验用
    page: int | None = None            # 选线用的代表性页 1-based；PDF 才有意义
    deskew_applied: bool = False       # split_x 是否是 deskew 后坐标
    notes: str = ""
```

#### Scenario: Construction with required fields only
- **WHEN** user constructs `ManualSplitProfile(split_x=450, source_size=(920, 700))`
- **THEN** `page` defaults to `None`, `deskew_applied` defaults to `False`, `notes` defaults to `""`

#### Scenario: Construction with all fields
- **WHEN** user constructs `ManualSplitProfile(split_x=450, source_size=(920, 700), page=1, deskew_applied=True, notes="尸子卷首页")`
- **THEN** all fields are preserved verbatim

#### Scenario: Frozen dataclass
- **WHEN** user attempts to mutate `profile.split_x = 500`
- **THEN** `dataclasses.FrozenInstanceError` is raised

---

### Requirement: `to_json` serialization (v1 schema)

`ManualSplitProfile.to_json()` MUST serialize to a v1 JSON string with stable key order:

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

- MUST use `ensure_ascii=False` (preserve Chinese notes)
- MUST emit `version: 1` first
- MUST use `sort_keys=False` (stable insertion order)
- MUST emit `source_size` as `[W, H]` (W first) when not `None`
- MUST omit `source_size` key when `None` is not allowed (always emit, possibly `null`)

#### Scenario: Round-trip via to_json → from_json
- **WHEN** user calls `p = ManualSplitProfile(split_x=450, source_size=(920, 700), page=1, deskew_applied=True)` then `s = p.to_json()` then `p2 = ManualSplitProfile.from_json(s)`
- **THEN** `p == p2` (all fields equal)

#### Scenario: Chinese notes preserved
- **WHEN** user constructs with `notes="尸子卷首页"`
- **THEN** `to_json()` output contains the literal Chinese string (no `\uXXXX` escape)

---

### Requirement: `from_json` deserialization (v1 schema, strict version)

`ManualSplitProfile.from_json(s)` MUST:
- Parse JSON string `s`
- Validate `version == 1`; otherwise raise `ValueError("unsupported preset version: {v}")` (error `MS006`)
- Extract `split_x` as int; otherwise raise `ValueError` with error `MS002`
- Validate `1 <= split_x < source_size[0]`; otherwise raise `ValueError` with error `MS001`
- Extract `source_size` as `[W, H]` of 2 ints
- Extract optional `page` (default `None`)
- Extract optional `deskew_applied` (default `False`)
- Extract optional `notes` (default `""`)

#### Scenario: Valid v1 JSON
- **WHEN** user parses `{"version":1, "split_x":450, "source_size":[920, 700]}` (no optional fields)
- **THEN** `ManualSplitProfile.from_json(s)` returns `ManualSplitProfile(split_x=450, source_size=(920, 700))`

#### Scenario: Invalid version
- **WHEN** user parses `{"version":2, "split_x":450, ...}`
- **THEN** `ValueError` is raised with message containing "MS006" and "unsupported preset version"

#### Scenario: split_x out of range (lower bound)
- **WHEN** user parses `{"version":1, "split_x":0, "source_size":[920, 700]}`
- **THEN** `ValueError` is raised with message containing "MS001"

#### Scenario: split_x out of range (upper bound)
- **WHEN** user parses `{"version":1, "split_x":920, "source_size":[920, 700]}`
- **THEN** `ValueError` is raised with message containing "MS001"

#### Scenario: Missing required field
- **WHEN** user parses `{"version":1, "source_size":[920, 700]}` (no `split_x`)
- **THEN** `KeyError` or `ValueError` is raised (both acceptable; document the message)

#### Scenario: Malformed JSON
- **WHEN** user passes string `"not json{"` to `from_json`
- **THEN** `json.JSONDecodeError` is raised (raw, not wrapped) — caller should catch and report as `MS005`

---

### Requirement: `apply_manual_split` function

`apply_manual_split(arr: np.ndarray, profile: ManualSplitProfile) -> list[np.ndarray]` MUST:
- Take a 2-D grayscale ndarray `arr` (H × W)
- Return `[arr[:, :split_x], arr[:, split_x:]]` as a list of 2 ndarrays
- If `profile.source_size is not None` and `(W, H) != profile.source_size`, emit a `logging.warning` with error code `MS003` and continue
- If `arr.shape[1] < 2`, raise `ValueError` (image too narrow to split)

#### Scenario: Normal split
- **WHEN** user calls `apply_manual_split(arr, ManualSplitProfile(split_x=450, source_size=(920, 700)))` on a 700×920 array
- **THEN** returns 2 sub-arrays of shapes `(700, 450)` and `(700, 470)`

#### Scenario: source_size mismatch (warn, not raise)
- **WHEN** user calls `apply_manual_split` with a profile whose `source_size=(920, 700)` but actual `arr.shape=(700, 1000)`
- **THEN** a `logging.warning` is emitted with code `MS003` and split still proceeds

#### Scenario: Image too narrow
- **WHEN** user calls `apply_manual_split` with `arr.shape=(100, 1)` (width=1)
- **THEN** `ValueError` is raised

---

### Requirement: CLI flag `--split manual`

The `--split` argument MUST accept `manual` as a new choice in addition to existing
`{none, half, gutter, border}`. The argparse `choices` becomes:
`["none", "half", "gutter", "border", "manual"]`.

#### Scenario: argparse accepts manual
- **WHEN** user runs `python -m book_cut -i x.pdf -o y --split manual --manual-split-x 450`
- **THEN** argparse parses successfully and `args.split == "manual"`

#### Scenario: argparse rejects unknown split values
- **WHEN** user runs `--split invalid`
- **THEN** argparse exits with code 2 and "invalid choice" error (no change from existing)

---

### Requirement: CLI flag `--manual-split-x N`

A new optional integer argument `--manual-split-x N` MUST be accepted when `--split manual`.

- Type: `int`
- Default: `None`
- Validation: `1 <= N < 4000` (sanity bound; warning not error)
- Conflicting flags: if both `--manual-split-x` and `--manual-split-preset` are provided, the preset MUST take precedence and a warning MUST be emitted

#### Scenario: Direct x value
- **WHEN** user runs `--split manual --manual-split-x 450`
- **THEN** `args.manual_split_x == 450`

#### Scenario: Both x and preset given
- **WHEN** user runs `--split manual --manual-split-x 450 --manual-split-preset p.json`
- **THEN** preset is used; `args.manual_split_x` value is ignored; a warning is printed to stderr

#### Scenario: Neither x nor preset given with --split manual
- **WHEN** user runs `--split manual` (no x, no preset)
- **THEN** pipeline MUST raise `ValueError` with error code `MS004` and exit 1

---

### Requirement: CLI flag `--manual-split-preset PATH`

A new optional string argument `--manual-split-preset PATH` MUST be accepted when `--split manual`.

- Default: `None`
- If the file does not exist or fails JSON parsing, the pipeline MUST exit 1 with error code `MS005`

#### Scenario: Preset file loaded
- **WHEN** user runs `--split manual --manual-split-preset preset.json` and the file contains valid v1 JSON
- **THEN** the profile is loaded via `ManualSplitProfile.from_json` and used for all pages

#### Scenario: Preset file missing
- **WHEN** user runs `--split manual --manual-split-preset nonexistent.json`
- **THEN** the pipeline exits 1 with `FileNotFoundError` wrapped in message containing "MS005"

#### Scenario: Preset file malformed JSON
- **WHEN** user runs `--split manual --manual-split-preset bad.json` containing `not json{`
- **THEN** the pipeline exits 1 with message containing "MS005" (catches `json.JSONDecodeError`)

---

### Requirement: CLI subcommand `--pick-split-line`

A new subcommand `--pick-split-line` MUST open a GUI dialog (`SplitLinePicker`) for
interactive line selection and write the result to a JSON file.

- Flags: `-i INPUT` (required, same as main command), `-o OUTPUT_JSON` (required, path to write preset)
- Behavior:
  1. Load the input via existing `iter_pages` (PDF → first page, image → that image)
  2. Apply the current `--deskew` setting to the page (if any)
  3. Open `SplitLinePicker` Toplevel with the post-deskew image
  4. On user confirm: write JSON preset to `OUTPUT_JSON`
  5. On user cancel: exit 0 with no file written, no error

#### Scenario: Pick line and save JSON
- **WHEN** user runs `python -m book_cut --pick-split-line -i book.pdf -o preset.json`
- **THEN** the GUI picker appears, user clicks on the canvas at x=450, clicks Confirm
- **THEN** `preset.json` is written with `{"version":1, "split_x":450, "source_size":[W,H], "page":1, "deskew_applied":<bool>}` (or `null` for image inputs)

#### Scenario: Cancel does not write file
- **WHEN** user opens picker and clicks Cancel (or closes window)
- **THEN** `OUTPUT_JSON` is NOT created; exit code is 0

#### Scenario: Zero pages input
- **WHEN** user runs `--pick-split-line -i empty.pdf -o preset.json` and the PDF has 0 pages
- **THEN** the pipeline exits 2 with error `MS008`

---

### Requirement: GUI integration in main window

The main GUI window's `split` combobox MUST include `manual` as a new option.

- When the user selects `manual`, a new button `选切分线...` MUST appear next to the combobox
- Clicking `选切分线...` MUST open the same `SplitLinePicker` Toplevel
- On confirm, the selected `split_x` MUST be stored in a `Tkinter.IntVar` and included in the `values` dict passed to the pipeline
- The stored value MUST be validated by the pipeline on run (no client-side range check; server-side is authoritative)

#### Scenario: Select manual in GUI
- **WHEN** user selects `manual` from the split combobox
- **THEN** the `选切分线...` button becomes visible (was hidden otherwise)

#### Scenario: Click pick button
- **WHEN** user clicks `选切分线...`
- **THEN** `SplitLinePicker` Toplevel opens with the first page of the loaded input

#### Scenario: Confirm picker
- **WHEN** user moves the line to x=450 and clicks Confirm
- **THEN** the GUI's hidden `manual_split_x` variable is set to 450 and the values dict includes `manual_split_x=450`

#### Scenario: User doesn't pick but runs anyway
- **WHEN** user selects `manual` in combobox but does NOT click the picker button
- **THEN** the pipeline run MUST fail with `MS004` (similar to CLI)

---

### Requirement: `SplitLinePicker` Toplevel behavior

A new class `SplitLinePicker(tk.Toplevel)` MUST be implemented in
`src/book_cut/split/picker_ui.py` (or `gui_canvas.py` if it fits).

- Constructor: `__init__(self, parent, image: PIL.Image.Image, initial_x: int | None = None, on_confirm: Callable[[int], None] | None = None)`
- Layout:
  - Top: label showing `x = N px (P.P%)` (live update)
  - Center: Canvas with the image scaled to fit window width
  - Right side: Spinbox for direct numeric input
  - Bottom: buttons `[确定] [保存为 preset...] [取消]`
- Interactions:
  - Mouse left-click / drag on canvas → moves line to click position
  - Mouse wheel → ±1 px (Shift+wheel → ±10 px)
  - Keyboard `←/→` → ±1 px
  - Keyboard `Home/End` → 0/W
  - Double-click on line → center
  - Spinbox manual edit → updates line position
- On confirm: invokes `on_confirm(x)` callback with the final x value, then destroys the Toplevel
- On cancel / window close: destroys the Toplevel without invoking callback

#### Scenario: Drag line on canvas
- **WHEN** user left-clicks at canvas coordinate (123, 200) on a 800×600 canvas representing a 920×700 image
- **THEN** the line moves to image x = `123 * (920 / 800)` = 141 (rounded), and the top label updates

#### Scenario: Wheel scroll
- **WHEN** user scrolls wheel up at current x=450
- **THEN** x becomes 449 (and label updates)

#### Scenario: Shift+wheel
- **WHEN** user scrolls wheel up with Shift held at current x=450
- **THEN** x becomes 440 (delta = -10)

#### Scenario: Spinbox edit
- **WHEN** user types `500` into the Spinbox and presses Enter
- **THEN** the canvas line moves to x=500

#### Scenario: Home key
- **WHEN** user presses Home at current x=450
- **THEN** x becomes 0 (or 1, the lower bound) and the line moves to the left edge

#### Scenario: Confirm
- **WHEN** user clicks `确定` at current x=450
- **THEN** `on_confirm(450)` is invoked and the Toplevel is destroyed

#### Scenario: Cancel
- **WHEN** user clicks `取消` or closes the window
- **THEN** the Toplevel is destroyed without invoking `on_confirm`

#### Scenario: Save as preset
- **WHEN** user clicks `保存为 preset...`
- **THEN** a file dialog opens; on file selection, a JSON preset is written with current x, source_size, page (1 if from picker), and deskew_applied (per current state)
- **THEN** the Toplevel remains open (user can continue editing after saving)

---

### Requirement: Pipeline integration (`orchestrator._compute_page`)

`_compute_page` MUST handle `split_strategy == "manual"` by:
1. Resolving the `ManualSplitProfile` (from preset JSON, or constructed from `args.manual_split_x`)
2. Calling `apply_manual_split(arr, profile)` to produce `sub_arrs`
3. Setting `split_x = profile.split_x` for metrics / preview
4. Setting `page_rects = None` (manual split doesn't compute page rects)

The function signature MUST be extended with:
- `manual_split_profile: ManualSplitProfile | None = None`

#### Scenario: manual split with preset
- **WHEN** `split_strategy="manual"` and `manual_split_profile=ManualSplitProfile(split_x=450, source_size=(920, 700))`
- **THEN** `sub_arrs` is `[arr[:, :450], arr[:, 450:]]` of shapes `(H, 450)` and `(H, 470)`
- **THEN** `split_x == 450` in the returned metrics dict

#### Scenario: manual split without profile (error)
- **WHEN** `split_strategy="manual"` and `manual_split_profile is None`
- **THEN** `_compute_page` MUST raise `ValueError` with message containing "MS004"

---

### Requirement: deskew_applied consistency check

When `--split manual` is used in the main pipeline run, the system MUST verify that
`profile.deskew_applied == bool(args.deskew)`. If they differ, exit 1 with `MS009`.

#### Scenario: Consistent (both deskew=True)
- **WHEN** `args.deskew=True` and `profile.deskew_applied=True`
- **THEN** pipeline proceeds normally

#### Scenario: Mismatch (preset deskew=False, run deskew=True)
- **WHEN** `args.deskew=True` and `profile.deskew_applied=False`
- **THEN** pipeline exits 1 with `ValueError` containing "MS009" and a hint to re-pick the line with `--deskew` enabled

#### Scenario: Mismatch (preset deskew=True, run deskew=False)
- **WHEN** `args.deskew=False` and `profile.deskew_applied=True`
- **THEN** pipeline exits 1 with `ValueError` containing "MS009"

#### Scenario: Consistent (both deskew=False)
- **WHEN** `args.deskew=False` and `profile.deskew_applied=False`
- **THEN** pipeline proceeds normally

---

### Requirement: Single-page input handling

When `auto_single_page=True` (default) detects that a page is already single-page
(no gutter found), and `--split manual` is enabled, the system MUST:
1. Emit a `logging.warning` with code `MS007` and the page number
2. Skip manual split for that page; treat the whole arr as `sub_arrs = [arr]` (length 1)
3. The remaining pipeline (crop / binarize) continues as for `--split none`

#### Scenario: Single-page detected, manual split enabled
- **WHEN** page 5 is detected as single-page (no gutter) and `split_strategy="manual"`
- **THEN** `sub_arrs == [arr]` for page 5
- **THEN** a warning containing "MS007" and "page 5" is emitted

#### Scenario: Multi-page, no exception
- **WHEN** all pages have gutter (not single-page)
- **THEN** no `MS007` warning is emitted and manual split applies to all

---

### Requirement: 1:3+ cross-page input warning (MS010)

When `apply_manual_split` (or the pipeline) detects that an image is a 1:3+ scan
(sub_arrs length would be > 2 by external analysis), the system MUST:
1. Emit a `logging.warning` with code `MS010`
2. Use the single `split_x` to slice the first two sub-arrays; treat the rest as a single third array

**v2.4 simplification**: this only applies to the orchestrator. `apply_manual_split` itself
always returns exactly 2 arrays (it doesn't auto-detect 1:3). The orchestrator wraps with
the MS010 warning before calling, based on a simple heuristic (e.g., `arr.shape[1] / 2 < profile.split_x`).

#### Scenario: 1:3 detection (wide image)
- **WHEN** `arr.shape[1] == 2400` and `profile.split_x == 800` (image is ~3x normal width)
- **THEN** a warning with "MS010" is emitted
- **THEN** sub_arrs = `[arr[:, :800], arr[:, 800:1600], arr[:, 1600:]]` (3 sub-arrays)

#### Scenario: Normal 1:2 (no warning)
- **WHEN** `arr.shape[1] == 920` and `profile.split_x == 450`
- **THEN** no MS010 warning; sub_arrs = `[arr[:, :450], arr[:, 450:]]`

---

## MODIFIED Requirements

### Requirement: `book_cut.split` package exports

The `src/book_cut/split/__init__.py` MUST export `apply_manual_split` and `ManualSplitProfile`
so that `from book_cut.split import ManualSplitProfile, apply_manual_split` works.

#### Scenario: Import from package
- **WHEN** `from book_cut.split import ManualSplitProfile, apply_manual_split` is executed
- **THEN** no `ImportError` is raised

---

### Requirement: README documentation

The `README.md` MUST include:
- A row in the "切分策略" section for `manual` with a one-line description
- A `--split manual` usage example in the "用法" section
- A note that `--pick-split-line` is a separate subcommand for interactive selection

#### Scenario: README has manual section
- **WHEN** user searches `README.md` for "manual"
- **THEN** at least 3 matches exist (CLI table row, usage example, picker mention)

---

### Requirement: CHANGELOG entry

`CHANGELOG.md` MUST include a `## [0.3.6]` section describing:
- New `--split manual` flag
- New `--manual-split-x` and `--manual-split-preset` flags
- New `--pick-split-line` subcommand
- New `SplitLinePicker` Toplevel
- New `MSxxx` error code series
- Backward compatibility note

#### Scenario: CHANGELOG has 0.3.6 entry
- **WHEN** user reads `CHANGELOG.md` top section
- **THEN** a `0.3.6` section is present and describes the new feature

---

## REMOVED Requirements

*None* — this change is purely additive.

## RENAMED Requirements

*None*.
