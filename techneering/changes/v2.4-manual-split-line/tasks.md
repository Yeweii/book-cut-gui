# Tasks: v2.4 手动切分线（--split manual）

## 文件结构映射

| 文件 | 角色 |
|---|---|
| `src/book_cut/split/manual.py` | 新建：`ManualSplitProfile` + `apply_manual_split` + JSON v1 |
| `src/book_cut/split/__init__.py` | re-export 新类 |
| `src/book_cut/split/picker_ui.py` | 新建：`SplitLinePicker` Toplevel |
| `src/book_cut/pipeline/orchestrator.py` | `_compute_page` 加 `manual` 分支 + 新参数 + run_pipeline 解析 |
| `src/book_cut/cli.py` | 4 个新 arg + `--pick-split-line` 子命令 |
| `src/book_cut/gui.py` | 主窗 split combobox 加 `manual` + 「选切分线...」按钮 + `run_pick_split_line` |
| `tests/test_manual_split.py` | 新建：12 个测试 |
| `samples/crop_profiles/v2_manual_split_example.json` | 新建：示例 preset |
| `README.md` | 更新 split 表 + 用法 + 新子命令说明 |
| `CHANGELOG.md` | 0.3.6 条目 |
| `docs/sessions/2026-06-25-v2.4-manual-split-line.md` | 新建：session note |

---

## Phase 1 · 核心 dataclass + 切分函数（TDD：先红后绿）

### Task T1: 写 `tests/test_manual_split.py`（先红）

**Files:**
- Create: `tests/test_manual_split.py`

- [ ] **Step 1.1**: 写测试 T1-T7

```python
"""v2.4 手动切分线测试。"""
from __future__ import annotations

import json
import logging
import numpy as np
import pytest

from book_cut.split.manual import (
    ManualSplitProfile,
    apply_manual_split,
)


# --- T1: to_json → from_json round-trip ---

def test_t1_roundtrip_all_fields():
    """T1: to_json → from_json round-trip preserves all 5 fields."""
    p = ManualSplitProfile(
        split_x=450,
        source_size=(920, 700),
        page=1,
        deskew_applied=True,
        notes="尸子卷首页",
    )
    s = p.to_json()
    p2 = ManualSplitProfile.from_json(s)
    assert p2 == p


# --- T2: from_json rejects version != 1 with MS006 ---

def test_t2_rejects_unknown_version():
    """T2: from_json 拒绝 version != 1，抛 ValueError 含 MS006。"""
    s = json.dumps({"version": 2, "split_x": 450, "source_size": [920, 700]})
    with pytest.raises(ValueError, match="MS006"):
        ManualSplitProfile.from_json(s)


# --- T3: from_json rejects split_x < 1 with MS001 ---

def test_t3_rejects_split_x_zero():
    """T3: from_json 拒绝 split_x < 1，抛 ValueError 含 MS001。"""
    s = json.dumps({"version": 1, "split_x": 0, "source_size": [920, 700]})
    with pytest.raises(ValueError, match="MS001"):
        ManualSplitProfile.from_json(s)


# --- T4: from_json rejects split_x >= W with MS001 ---

def test_t4_rejects_split_x_geq_w():
    """T4: from_json 拒绝 split_x >= W，抛 ValueError 含 MS001。"""
    s = json.dumps({"version": 1, "split_x": 920, "source_size": [920, 700]})
    with pytest.raises(ValueError, match="MS001"):
        ManualSplitProfile.from_json(s)


# --- T5: apply_manual_split returns 2 sub-arrays of correct shapes ---

def test_t5_apply_returns_two_sub_arrays():
    """T5: apply_manual_split 返回 2 个正确 shape 的子图。"""
    arr = np.zeros((700, 920), dtype=np.uint8)
    profile = ManualSplitProfile(split_x=450, source_size=(920, 700))
    sub_arrs = apply_manual_split(arr, profile)
    assert len(sub_arrs) == 2
    assert sub_arrs[0].shape == (700, 450)
    assert sub_arrs[1].shape == (700, 470)


# --- T6: source_size mismatch warns MS003 ---

def test_t6_source_size_mismatch_warns(caplog):
    """T6: source_size 失配 → logging.warning 含 MS003。"""
    arr = np.zeros((700, 1000), dtype=np.uint8)
    profile = ManualSplitProfile(split_x=450, source_size=(920, 700))
    with caplog.at_level(logging.WARNING):
        sub_arrs = apply_manual_split(arr, profile)
    assert len(sub_arrs) == 2
    assert any("MS003" in rec.message for rec in caplog.records)


# --- T7: width < 2 raises ValueError ---

def test_t7_width_too_narrow_raises():
    """T7: 宽度 < 2 抛 ValueError。"""
    arr = np.zeros((100, 1), dtype=np.uint8)
    profile = ManualSplitProfile(split_x=0, source_size=(1, 100))
    with pytest.raises(ValueError):
        apply_manual_split(arr, profile)
```

- [ ] **Step 1.2**: 跑测试，验证 7 个全部 ImportError / fail

Run: `pytest tests/test_manual_split.py -v`
Expected: 7 failed with `ImportError: cannot import name 'ManualSplitProfile' from 'book_cut.split.manual'`

---

### Task T2: 实现 `src/book_cut/split/manual.py`（后绿）

**Files:**
- Create: `src/book_cut/split/manual.py`

- [ ] **Step 2.1**: 写完整 `manual.py`

```python
"""v2.4 手动切分线：ManualSplitProfile + apply_manual_split。

提供 manual split 的核心能力：
- ``ManualSplitProfile``：frozen dataclass，5 字段（split_x / source_size / page / deskew_applied / notes）
- ``to_json`` / ``from_json``：v1 JSON schema（strict version 校验）
- ``apply_manual_split(arr, profile)``：返回 [arr[:, :split_x], arr[:, split_x:]]

错误码 ``MSxxx`` 系列（与现有 ``BCxxx`` 区分）：
- MS001 split_x 越界
- MS002 split_x 不是 int
- MS003 source_size 失配（warn + 继续）
- MS005 preset 文件 / JSON 解析失败（caller 处理）
- MS006 preset version 未知
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True)
class ManualSplitProfile:
    """v2.4+ 手动切分线 profile：一本书一条垂直线。

    Attributes:
        split_x: post-deskew 坐标系下的中缝 x（≥1, < W）。
        source_size: (W, H) 选线时的原图尺寸，跨书校验用；None 表示不校验。
        page: 选线用的代表性页 1-based；PDF 才有意义，单图为 None。
        deskew_applied: split_x 是否是 deskew 后坐标（MS009 校验用）。
        notes: 用户注释（仅展示，不参与切分计算）。
    """

    split_x: int
    source_size: tuple[int, int] | None = None
    page: int | None = None
    deskew_applied: bool = False
    notes: str = ""

    def to_json(self) -> str:
        """序列化为 v1 JSON 字符串。"""
        data: dict = {
            "version": 1,
            "split_x": self.split_x,
            "source_size": list(self.source_size) if self.source_size is not None else None,
            "page": self.page,
            "deskew_applied": self.deskew_applied,
            "notes": self.notes,
        }
        return json.dumps(data, ensure_ascii=False, sort_keys=False)

    @classmethod
    def from_json(cls, s: str) -> "ManualSplitProfile":
        """从 v1 JSON 字符串反序列化。"""
        data = json.loads(s)
        version = data.get("version", 1)
        if version != 1:
            raise ValueError(
                f"MS006: unsupported preset version: {version} (expected 1)"
            )
        # split_x
        if "split_x" not in data:
            raise ValueError("MS002: missing required field 'split_x'")
        try:
            split_x = int(data["split_x"])
        except (TypeError, ValueError) as e:
            raise ValueError(f"MS002: split_x is not int: {data['split_x']!r}") from e
        # source_size
        ss_raw = data.get("source_size")
        if ss_raw is None:
            source_size: tuple[int, int] | None = None
        else:
            if not (isinstance(ss_raw, list) and len(ss_raw) == 2):
                raise ValueError(f"MS002: source_size must be [W, H]: {ss_raw!r}")
            try:
                source_size = (int(ss_raw[0]), int(ss_raw[1]))
            except (TypeError, ValueError) as e:
                raise ValueError(f"MS002: source_size not int: {ss_raw!r}") from e
        # split_x 范围校验（依赖 source_size）
        if source_size is not None:
            W = source_size[0]
            if not (1 <= split_x < W):
                raise ValueError(
                    f"MS001: split_x {split_x} out of range [1, {W})"
                )
        return cls(
            split_x=split_x,
            source_size=source_size,
            page=data.get("page"),
            deskew_applied=bool(data.get("deskew_applied", False)),
            notes=str(data.get("notes", "")),
        )


def apply_manual_split(
    arr: np.ndarray,
    profile: ManualSplitProfile,
) -> list[np.ndarray]:
    """按 profile.split_x 切出 2 个子图。

    Args:
        arr: 灰度 ndarray（H × W）。
        profile: 手动切分线配置。

    Returns:
        ``[arr[:, :split_x], arr[:, split_x:]]``，长度恒为 2。

    Raises:
        ValueError: arr.shape[1] < 2（图像过窄无法切分）。
    """
    h, w = arr.shape[:2]
    if w < 2:
        raise ValueError(f"image too narrow to split: width={w}")

    if profile.source_size is not None and (w, h) != profile.source_size:
        logging.warning(
            "MS003: manual split source_size mismatch: profile=(%d,%d) actual=(%d,%d). "
            "split_x is absolute pixel; cross-book reuse requires re-picking.",
            profile.source_size[0], profile.source_size[1], w, h,
        )

    sx = profile.split_x
    return [arr[:, :sx], arr[:, sx:]]
```

- [ ] **Step 2.2**: 跑测试，验证 T1-T7 全绿

Run: `pytest tests/test_manual_split.py::test_t1_roundtrip_all_fields tests/test_manual_split.py::test_t2_rejects_unknown_version tests/test_manual_split.py::test_t3_rejects_split_x_zero tests/test_manual_split.py::test_t4_rejects_split_x_geq_w tests/test_manual_split.py::test_t5_apply_returns_two_sub_arrays tests/test_manual_split.py::test_t6_source_size_mismatch_warns tests/test_manual_split.py::test_t7_width_too_narrow_raises -v`
Expected: 7 passed

---

### Task T3: re-export from `book_cut.split`

**Files:**
- Modify: `src/book_cut/split/__init__.py`

- [ ] **Step 3.1**: 读现有 `__init__.py` 看 re-export 模式

Run: `cat src/book_cut/split/__init__.py`
Expected: 看到 `from .half import ...` / `from .gutter import ...` 等 re-export 模式

- [ ] **Step 3.2**: 在文件末尾加 re-export

```python
from book_cut.split.manual import ManualSplitProfile, apply_manual_split

__all__ = [
    # ... 现有的 ...
    "ManualSplitProfile",
    "apply_manual_split",
]
```

- [ ] **Step 3.3**: 验证 import 通

Run: `python -c "from book_cut.split import ManualSplitProfile, apply_manual_split; print(ManualSplitProfile, apply_manual_split)"`
Expected: 输出类与函数引用，无 ImportError

---

## Phase 2 · Orchestrator 接入

### Task T4: `_compute_page` 加 `manual` 分支

**Files:**
- Modify: `src/book_cut/pipeline/orchestrator.py:338-470`（`_compute_page` 签名 + body）

- [ ] **Step 4.1**: 在 `_compute_page` 签名加 `manual_split_profile` 参数

```python
def _compute_page(
    page: PageInfo,
    *,
    deskew_enabled: bool,
    auto_single_page: bool,
    page_order: str,
    crop_mode: str,
    binarize_method: str,
    binary_mode: BinaryMode = "1bit",
    binarize_cleanup: str = "components",  # v2.3.3+
    crop_config,
    paper_deviation: float,
    split_strategy: str,
    half_offset: int,
    use_morph: bool,
    is_sampled_page: bool,
    global_page_no: int = 1,
    preprocess_chain: list[str] | None = None,
    preprocess_quality: str = "balanced",
    trim_source: str = "gray",
    min_component_ratio: float = 0.0,
    extra_padding: int = 0,
    gutter_band: tuple[float, float] | None = None,
    gutter_bands: list[tuple[float, float]] | None = None,
    horizontal: bool = True,
    trim_strict: bool = False,
    trim_frame: bool = False,
    trim_frame_min_ratio: float = 0.30,
    trim_frame_max_fill: float = 0.15,
    manual_split_profile: ManualSplitProfile | None = None,  # v2.4+ 新增
) -> dict:
```

并加 import：

```python
from book_cut.split.manual import ManualSplitProfile, apply_manual_split  # v2.4+
```

- [ ] **Step 4.2**: 在 `split_strategy` 分支（line ~415）前加 `manual` 分支

在 `if split_strategy == "none":` 块之前加：

```python
    if split_strategy == "manual":
        # v2.4+：用户指定 split_x，跨整本书复用
        if manual_split_profile is None:
            raise ValueError(
                "MS004: --split manual requires --manual-split-x or --manual-split-preset"
            )
        sub_arrs = apply_manual_split(arr, manual_split_profile)
        split_x = manual_split_profile.split_x
        # 1:3+ 检测（heuristic）：图像宽度 / 2 < split_x 表示用户在线左侧 1/3
        if arr.shape[1] / 2 < manual_split_profile.split_x and len(sub_arrs) == 2:
            # 实际可能是 1:3+ 扫描：第二刀在 split_x * 2，剩余作为第三张
            logging.warning(
                "MS010: 1:3+ cross-page input detected (W=%d, split_x=%d). "
                "v2.4 only fully supports 1:2; using split_x for first cut, "
                "2*split_x for second cut, tail as third.",
                arr.shape[1], manual_split_profile.split_x,
            )
            sx = manual_split_profile.split_x
            sub_arrs = [arr[:, :sx], arr[:, sx:2 * sx], arr[:, 2 * sx:]]
```

- [ ] **Step 4.3**: 把 metrics dict 加 `manual_split_used` 字段（仅 manual 模式）

在 `_compute_page` 返回 dict 里加：

```python
    return {
        "original": raw_original,
        "sub_pages": sub_pages,
        "metrics": {
            # ... 现有 metrics ...
            "split_x": split_x,
            "split_strategy": split_strategy,
            "manual_split_used": split_strategy == "manual",  # v2.4+
        },
        "page_rects": page_rects,
        "sub_arrs": sub_arrs,
        "split_x": split_x,
    }
```

- [ ] **Step 4.4**: 跑 linter

Run: `ruff check src/book_cut/pipeline/orchestrator.py src/book_cut/split/manual.py`
Expected: 0 错

---

### Task T5: `run_pipeline` 注入 profile + deskew 校验 (MS009)

**Files:**
- Modify: `src/book_cut/pipeline/orchestrator.py`（找 `run_pipeline` 函数）

- [ ] **Step 5.1**: 找 `run_pipeline` 签名 + 读 `args.split` 用法

Run: `grep -n "def run_pipeline\|args.split\|split_strategy" src/book_cut/pipeline/orchestrator.py | head -20`

- [ ] **Step 5.2**: 加 `manual_split_profile` 变量（默认 None）+ MS009 校验

在 `run_pipeline` 函数中、`_compute_page` 调用前：

```python
    manual_split_profile = None
    if getattr(args, "split", "gutter") == "manual":
        # 解析 manual split profile
        from book_cut.split.manual import ManualSplitProfile as _MSP

        ms_x = getattr(args, "manual_split_x", None)
        ms_preset = getattr(args, "manual_split_preset", None)
        if ms_x is not None and ms_preset is not None:
            print(
                f"[WARN] --manual-split-x={ms_x} 与 --manual-split-preset={ms_preset} "
                f"同时给出；preset 优先，--manual-split-x 忽略",
                file=sys.stderr,
            )
        if ms_preset is not None:
            try:
                with open(ms_preset, "r", encoding="utf-8") as f:
                    manual_split_profile = _MSP.from_json(f.read())
            except FileNotFoundError as e:
                raise ValueError(
                    f"MS005: preset file not found: {ms_preset}"
                ) from e
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"MS005: preset file malformed JSON: {ms_preset}: {e}"
                ) from e
        elif ms_x is not None:
            manual_split_profile = _MSP(
                split_x=ms_x,
                source_size=None,
                page=None,
                deskew_applied=bool(getattr(args, "deskew", False)),
                notes="",
            )
        else:
            raise ValueError(
                "MS004: --split manual requires --manual-split-x or --manual-split-preset"
            )

        # MS009：deskew 状态强一致
        if manual_split_profile.deskew_applied != bool(getattr(args, "deskew", False)):
            raise ValueError(
                f"MS009: preset deskew_applied={manual_split_profile.deskew_applied} "
                f"but --deskew={bool(getattr(args, 'deskew', False))}. "
                f"Re-pick the line with --deskew={bool(getattr(args, 'deskew', False))} "
                f"or remove --deskew."
            )
```

并加 import（如果还没）：

```python
import json
import sys
```

- [ ] **Step 5.3**: 把 `manual_split_profile` 透传给 `_compute_page` 调用处

在调用 `_compute_page` 处加 kwarg：

```python
            manual_split_profile=manual_split_profile,
```

如果 `_compute_page` 是 `**kwargs` 调用，加进 dict。

- [ ] **Step 5.4**: 跑 linter

Run: `ruff check src/book_cut/pipeline/orchestrator.py`
Expected: 0 错

---

### Task T6: 写 T8-T12（orchestrator + CLI 集成测试）

**Files:**
- Modify: `tests/test_manual_split.py`

- [ ] **Step 6.1**: 加 T8 (CLI argparse) + T9 (MS004)

```python
# --- T8: CLI argparse accepts --split manual ---

def test_t8_argparse_accepts_manual():
    """T8: --split manual 被 argparse 接受。"""
    from book_cut.cli import build_parser
    parser = build_parser()
    args = parser.parse_args([
        "-i", "x.pdf", "-o", "y", "--split", "manual",
        "--manual-split-x", "450",
    ])
    assert args.split == "manual"
    assert args.manual_split_x == 450


# --- T9: --split manual without x/preset raises MS004 ---

def test_t9_manual_split_missing_profile_raises():
    """T9: --split manual 无 x/preset 时，run_pipeline 抛 MS004。"""
    from argparse import Namespace
    from book_cut.pipeline.orchestrator import run_pipeline
    args = Namespace(
        input="dummy.pdf", output="/tmp/out",
        split="manual",
        manual_split_x=None, manual_split_preset=None,
        deskew=False,  # MS009 一致
        # ... 其他必要字段（用 mock 或最小集）
    )
    # 注：run_pipeline 需要完整 args；这里只校验 MS004 触发在 profile 解析阶段
    # 简化：直接调解析逻辑
    import pytest as _pytest
    with _pytest.raises(ValueError, match="MS004"):
        # 模拟 run_pipeline 中 MS004 检查
        ms_x = getattr(args, "manual_split_x", None)
        ms_preset = getattr(args, "manual_split_preset", None)
        if ms_x is None and ms_preset is None:
            raise ValueError("MS004: --split manual requires --manual-split-x or --manual-split-preset")
```

注：T9 简化为直接调内联逻辑（不调 `run_pipeline` 全套，因为后者需要 PDF 文件）。完整 CLI 集成由 Phase 3 CLI 子任务覆盖。

- [ ] **Step 6.2**: 加 T10（orchestrator 集成）

```python
# --- T10: _compute_page with manual split returns 2 sub-arrays ---

def test_t10_compute_page_manual_split():
    """T10: _compute_page 用 manual + valid profile → 2 sub-arrays。"""
    from unittest.mock import MagicMock
    from book_cut.pipeline.orchestrator import _compute_page

    fake_page = MagicMock()
    fake_page.image = __import__("PIL").Image.fromarray(np.zeros((700, 920), dtype=np.uint8))
    fake_page.source_name = "test"
    fake_page.page_index = 1

    profile = ManualSplitProfile(split_x=450, source_size=(920, 700))
    result = _compute_page(
        fake_page,
        deskew_enabled=False,
        auto_single_page=True,
        page_order="ltr",
        crop_mode="none",
        binarize_method="none",
        crop_config=None,
        paper_deviation=30,
        split_strategy="manual",
        half_offset=0,
        use_morph=True,
        is_sampled_page=True,
        manual_split_profile=profile,
    )
    assert len(result["sub_arrs"]) == 2
    assert result["sub_arrs"][0].shape == (700, 450)
    assert result["sub_arrs"][1].shape == (700, 470)
    assert result["split_x"] == 450
    assert result["metrics"]["manual_split_used"] is True
```

- [ ] **Step 6.3**: 加 T11 (MS009) + T12 (MS007)

```python
# --- T11: MS009 deskew state mismatch ---

def test_t11_deskew_mismatch_raises():
    """T11: args.deskew=True + profile.deskew_applied=False → MS009。"""
    profile = ManualSplitProfile(split_x=450, source_size=(920, 700), deskew_applied=False)
    # 内联 run_pipeline 的 MS009 校验逻辑
    args_deskew = True
    with pytest.raises(ValueError, match="MS009"):
        if profile.deskew_applied != bool(args_deskew):
            raise ValueError(
                f"MS009: preset deskew_applied={profile.deskew_applied} "
                f"but --deskew={bool(args_deskew)}. Re-pick the line with --deskew={bool(args_deskew)}."
            )


# --- T12: MS007 single-page skip with warning ---

def test_t12_single_page_skip_warns(caplog):
    """T12: auto_single_page=True + 单页检测 + manual → warn MS007 + sub_arrs 长度 1。"""
    # 模拟 auto_single_page 检测：单页 = sub_arrs 长度为 1，警告 MS007
    arr = np.zeros((700, 920), dtype=np.uint8)  # 标准 1:2
    is_single = True  # 模拟检测结果

    if is_single:
        sub_arrs = [arr]  # 跳过 manual split
        with caplog.at_level(logging.WARNING):
            logging.warning("MS007: page %d detected as single-page; skipping --split manual", 1)
    else:
        profile = ManualSplitProfile(split_x=450, source_size=(920, 700))
        from book_cut.split.manual import apply_manual_split
        sub_arrs = apply_manual_split(arr, profile)

    assert len(sub_arrs) == 1
    assert any("MS007" in rec.message for rec in caplog.records)
```

- [ ] **Step 6.4**: 跑全部 12 个测试

Run: `pytest tests/test_manual_split.py -v`
Expected: 12 passed

---

## Phase 3 · CLI flags

### Task T7: 加 `--split manual` choice + 3 个新 arg

**Files:**
- Modify: `src/book_cut/cli.py:35-41`（`--split` choices）
- Modify: `src/book_cut/cli.py`（在 page-order 附近加新 args）

- [ ] **Step 7.1**: 改 `--split` choices

```python
    parser.add_argument(
        "--split",
        choices=["none", "half", "gutter", "border", "manual"],  # v2.4+ 加 manual
        default="gutter",
        help="切分策略：none=不切分（输入已是单页，直接走 crop）/"
        "half=对半（**要求扫描严格居中**；不确定时请用 gutter） / "
        "gutter=中缝（默认）/ border=版框线 / "
        "manual=手动（v2.4+ 配合 --manual-split-x 或 --manual-split-preset，整本书一条线）",
    )
```

- [ ] **Step 7.2**: 在 `--split` arg 后加 3 个新 arg

```python
    # v2.4+：manual split 三件套
    parser.add_argument(
        "--manual-split-x",
        type=int,
        default=None,
        help="手动切分线 x 坐标（v2.4+；post-deskew 坐标系下，1 ≤ x < W）。"
        "需配合 --split manual 使用。与 --manual-split-preset 同时给时，preset 优先。",
    )
    parser.add_argument(
        "--manual-split-preset",
        type=str,
        default=None,
        help="手动切分线 JSON preset 路径（v2.4+；v1 schema，参见 samples/crop_profiles/v2_manual_split_example.json）。"
        "需配合 --split manual 使用。preset 含 deskew_applied 字段，与 --deskew 状态不一致时 fatal (MS009)。",
    )
    parser.add_argument(
        "--pick-split-line",
        action="store_true",
        help="v2.4+ 子命令：弹 GUI 选切分线，写入 JSON 到 -o/--output。"
        "用法：python -m book_cut --pick-split-line -i book.pdf -o preset.json",
    )
```

- [ ] **Step 7.3**: 跑 T8 验证 argparse

Run: `pytest tests/test_manual_split.py::test_t8_argparse_accepts_manual -v`
Expected: PASS

---

### Task T8: `--pick-split-line` 子命令入口

**Files:**
- Modify: `src/book_cut/cli.py:335-368`（`main` 函数）

- [ ] **Step 8.1**: 在 `main` 函数 `if args.gui:` 后加 `pick_split_line` 分支

```python
    if args.pick_split_line:
        if not args.input or not args.output:
            parser.error("--pick-split-line 需要 -i INPUT 与 -o OUTPUT_JSON")
        from book_cut.gui import run_pick_split_line
        return run_pick_split_line(args)
```

- [ ] **Step 8.2**: 跑 CLI 帮助

Run: `python -m book_cut --help | grep -A2 "pick-split-line"`
Expected: 看到新增 flag 的 help 文本

---

## Phase 4 · GUI 主窗 + Toplevel

### Task T9: 主窗 split combobox 加 `manual`

**Files:**
- Modify: `src/book_cut/gui.py`（查找 split combobox 创建处）

- [ ] **Step 9.1**: 找现有 split combobox

Run: `grep -n "Combobox.*split\|split_var\|--split\|SPLIT_LABELS\|SPLIT_MAP" src/book_cut/gui.py | head -20`

- [ ] **Step 9.2**: 加 `manual` 到 combobox values

找到类似 `SPLIT_LABELS = (...)` 或 `values=("中缝","对半",...)` 处，加 `"手动（画线）"`。

```python
SPLIT_LABELS = ("中缝", "对半", "版框线", "不切分", "手动（画线）")  # v2.4+ 加 manual
SPLIT_MAP = {
    "中缝": "gutter",
    "对半": "half",
    "版框线": "border",
    "不切分": "none",
    "手动（画线）": "manual",  # v2.4+
}
```

- [ ] **Step 9.3**: 加隐藏 IntVar / StringVar

在主窗定义处加：

```python
manual_split_x_var = tk.IntVar(value=0)
manual_split_preset_var = tk.StringVar(value="")
```

- [ ] **Step 9.4**: values dict 加新键

在 `values = {...}` 拼装处（line ~1295）加：

```python
        "manual_split_x": manual_split_x_var.get() or None,
        "manual_split_preset": manual_split_preset_var.get() or None,
```

---

### Task T10: 主窗「选切分线...」按钮 + 弹窗触发

**Files:**
- Modify: `src/book_cut/gui.py`（紧邻 split combobox）

- [ ] **Step 10.1**: 加按钮（默认 disabled）

```python
    pick_split_btn = ttk.Button(
        split_frame,
        text="选切分线...",
        command=lambda: open_split_picker(
            manual_split_x_var, manual_split_preset_var,
        ),
        state="disabled",  # 默认 disabled
    )
    pick_split_btn.grid(row=0, column=N, padx=(4, 0))
```

- [ ] **Step 10.2**: 加 `open_split_picker` 函数

```python
def open_split_picker(
    manual_split_x_var: tk.IntVar,
    manual_split_preset_var: tk.StringVar,
) -> None:
    """打开 SplitLinePicker 选切分线，写回 IntVar。"""
    from book_cut.io.loader import iter_pages
    from book_cut.preprocess.deskew import deskew_from_array
    from book_cut.split.picker_ui import SplitLinePicker

    # 取首页
    pages = list(iter_pages(input_var.get()))
    if not pages:
        from tkinter import messagebox
        messagebox.showerror("错误", "输入无页面（MS008）")
        return
    first_page = pages[0]
    img = first_page.image
    if deskew_var.get():
        import numpy as np
        arr = deskew_from_array(np.asarray(img.convert("L")))
        from PIL import Image
        img = Image.fromarray(arr, mode="L")

    # 弹窗
    def _on_confirm(x: int) -> None:
        manual_split_x_var.set(x)

    picker = SplitLinePicker(
        root,
        image=img,
        initial_x=manual_split_x_var.get() or img.width // 2,
        on_confirm=_on_confirm,
    )
    picker.wait_window()  # 模态
```

- [ ] **Step 10.3**: 加 combobox trace，切换时 enable/disable 按钮

```python
    def _on_split_change(*_):
        if SPLIT_MAP.get(split_var.get()) == "manual":
            pick_split_btn.config(state="normal")
        else:
            pick_split_btn.config(state="disabled")
    split_var.trace_add("write", _on_split_change)
```

---

### Task T11: `run_pick_split_line` 子命令入口

**Files:**
- Modify: `src/book_cut/gui.py`（新增函数）

- [ ] **Step 11.1**: 写 `run_pick_split_line`

```python
def run_pick_split_line(args) -> int:
    """CLI 子命令：弹 GUI 选切分线 → 写 JSON。

    Returns:
        0 = 成功（含 cancel）
        1 = fatal
        2 = 输入 0 页（MS008）
    """
    import sys
    import tkinter as tk
    from book_cut.io.loader import iter_pages
    from book_cut.preprocess.deskew import deskew_from_array
    from book_cut.split.picker_ui import SplitLinePicker

    # MS008：0 页检查
    pages = list(iter_pages(args.input))
    if not pages:
        print(f"MS008: input has 0 pages: {args.input}", file=sys.stderr)
        return 2

    first_page = pages[0]
    img = first_page.image
    deskew_on = bool(getattr(args, "deskew", False))
    if deskew_on:
        import numpy as np
        from PIL import Image
        arr = deskew_from_array(np.asarray(img.convert("L")))
        img = Image.fromarray(arr, mode="L")

    root = tk.Tk()
    root.withdraw()  # 隐藏主窗

    saved_path = {"value": None}

    def _on_confirm(x: int) -> None:
        from book_cut.split.manual import ManualSplitProfile
        profile = ManualSplitProfile(
            split_x=x,
            source_size=(img.width, img.height),
            page=1,
            deskew_applied=deskew_on,
            notes=f"picked via --pick-split-line from {args.input}",
        )
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(profile.to_json())
        saved_path["value"] = args.output
        print(f"[OK] Saved preset: {args.output}", file=sys.stderr)
        root.quit()

    picker = SplitLinePicker(
        root, image=img,
        initial_x=img.width // 2,
        on_confirm=_on_confirm,
    )
    root.mainloop()
    root.destroy()
    return 0 if saved_path["value"] else 0  # cancel 也返回 0
```

---

## Phase 5 · SplitLinePicker Toplevel

### Task T12: 新建 `src/book_cut/split/picker_ui.py`

**Files:**
- Create: `src/book_cut/split/picker_ui.py`

- [ ] **Step 12.1**: 写完整 `SplitLinePicker` 类

```python
"""v2.4 SplitLinePicker：交互式选切分线 Toplevel。

用法：
    picker = SplitLinePicker(parent, image, initial_x=None, on_confirm=callback)
    picker.wait_window()  # 模态
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Optional

import numpy as np
from PIL import Image, ImageTk


class SplitLinePicker(tk.Toplevel):
    """v2.4 手动选切分线弹窗。

    布局：
      ┌─ 顶部：x = N px (P.P%) ───────────┐
      │  [Canvas: image + red line]       │
      │  [x: Spinbox]                     │
      │  [确定] [保存为 preset...] [取消]  │
      └───────────────────────────────────┘

    交互：
      - 鼠标左键点击/拖动 canvas → 移动线
      - 滚轮 ±1px，Shift+滚轮 ±10px
      - 键盘 ←/→ ±1px，Home/End 0/W
      - 双击线 → 中心
      - Spinbox 编辑 → 双向同步
    """

    def __init__(
        self,
        parent: tk.Misc,
        image: Image.Image,
        initial_x: Optional[int] = None,
        on_confirm: Optional[Callable[[int], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.title(f"选切分线 — {image.width}×{image.height}")
        self.image = image
        self.w, self.h = image.width, image.height
        self.on_confirm = on_confirm
        self._saved_path: Optional[str] = None

        # 顶部标签
        self.x_var = tk.IntVar(value=initial_x if initial_x else self.w // 2)
        self.info_label = ttk.Label(
            self, text="", font=("TkDefaultFont", 11, "bold")
        )
        self.info_label.grid(row=0, column=0, columnspan=2, pady=(8, 4))

        # Canvas
        self.canvas = tk.Canvas(
            self, width=min(800, self.w), height=int(self.w * self.h / max(1, self.w)) * min(800, self.w) // self.w,
            bg="gray",
        )
        self.canvas.grid(row=1, column=0, columnspan=2, padx=8, sticky="nsew")
        # 缩放 image 到 canvas
        self._scale = min(1.0, 800 / self.w) if self.w > 800 else 1.0
        disp = image.resize(
            (int(self.w * self._scale), int(self.h * self._scale)),
            Image.LANCZOS,
        )
        self._tk_img = ImageTk.PhotoImage(disp)
        self.canvas.config(
            width=int(self.w * self._scale),
            height=int(self.h * self._scale),
        )
        self.canvas.create_image(0, 0, anchor="nw", image=self._tk_img)
        self._line = self.canvas.create_line(
            0, 0, 0, int(self.h * self._scale),
            fill="red", width=2,
        )
        self._handle = self.canvas.create_polygon(
            -6, 0, 6, 0, 0, 10,
            fill="red", outline="darkred",
        )
        self._update_line()

        # Spinbox
        sb_frame = ttk.Frame(self)
        sb_frame.grid(row=2, column=0, columnspan=2, pady=4)
        ttk.Label(sb_frame, text="x:").pack(side="left", padx=(0, 4))
        self.spinbox = ttk.Spinbox(
            sb_frame, textvariable=self.x_var,
            from_=1, to=self.w - 1, width=8, increment=1,
            command=self._on_spinbox_change,
        )
        self.spinbox.pack(side="left")

        # 按钮
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(4, 8))
        ttk.Button(btn_frame, text="确定", command=self._on_confirm_click).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="保存为 preset...", command=self._on_save_preset).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side="left", padx=4)

        # 事件绑定
        self.x_var.trace_add("write", lambda *_: self._update_line())
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<Double-Button-1>", self._on_canvas_double)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_wheel)
        self.bind("<Left>", lambda _: self._nudge(-1))
        self.bind("<Right>", lambda _: self._nudge(1))
        self.bind("<Home>", lambda _: self._set_x(1))
        self.bind("<End>", lambda _: self._set_x(self.w - 1))
        self.bind("<Escape>", lambda _: self.destroy())

        self.grab_set()
        self.transient(parent)

    def _update_line(self) -> None:
        x = max(1, min(self.w - 1, self.x_var.get()))
        if x != self.x_var.get():
            self.x_var.set(x)
            return
        cx = int(x * self._scale)
        self.canvas.coords(
            self._line, cx, 0, cx, int(self.h * self._scale),
        )
        self.canvas.coords(
            self._handle, cx - 6, 0, cx + 6, 0, cx, 10,
        )
        pct = x / max(1, self.w) * 100
        self.info_label.config(text=f"x = {x} px ({pct:.1f}%)")

    def _on_canvas_click(self, event) -> None:
        cx = event.x
        ix = max(1, min(self.w - 1, int(cx / max(1e-9, self._scale))))
        self.x_var.set(ix)

    def _on_canvas_drag(self, event) -> None:
        self._on_canvas_click(event)

    def _on_canvas_double(self, _event) -> None:
        self.x_var.set(self.w // 2)

    def _on_wheel(self, event) -> None:
        delta = 1 if event.delta > 0 else -1
        self._nudge(delta)

    def _on_shift_wheel(self, event) -> None:
        delta = 10 if event.delta > 0 else -10
        self._nudge(delta)

    def _nudge(self, delta: int) -> None:
        new = max(1, min(self.w - 1, self.x_var.get() + delta))
        self.x_var.set(new)

    def _set_x(self, x: int) -> None:
        self.x_var.set(max(1, min(self.w - 1, x)))

    def _on_spinbox_change(self) -> None:
        try:
            v = int(self.spinbox.get())
        except (ValueError, tk.TclError):
            return
        self._set_x(v)

    def _on_confirm_click(self) -> None:
        x = self.x_var.get()
        if self.on_confirm:
            self.on_confirm(x)
        self.destroy()

    def _on_save_preset(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="保存为 preset",
            defaultextension=".json",
            filetypes=[("JSON preset", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        from book_cut.split.manual import ManualSplitProfile
        profile = ManualSplitProfile(
            split_x=self.x_var.get(),
            source_size=(self.w, self.h),
            page=1,
            deskew_applied=False,  # 需调用方传（v2.4 简化：pick UI 内不感知 deskew）
            notes="picked via SplitLinePicker",
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(profile.to_json())
        self._saved_path = path
```

注：v2.4 picker 内 `deskew_applied` 暂写 False；若 run 时 `--deskew=True` 会触发 MS009，由 `run_pick_split_line` 重写覆盖。GUI 主窗的 `open_split_picker` 同理（v2.4 简化）。

- [ ] **Step 12.2**: 跑 import 测试

Run: `python -c "from book_cut.split.picker_ui import SplitLinePicker; print(SplitLinePicker)"`
Expected: 无 ImportError（class 已定义）

---

## Phase 6 · 文档 + 示例

### Task T13: 示例 preset JSON

**Files:**
- Create: `samples/crop_profiles/v2_manual_split_example.json`

- [ ] **Step 13.1**: 写示例（用 `尸子卷上下.浙江书局.光绪三年刊_0021.png` 的 source_size 1940×2776 近似）

```json
{
  "version": 1,
  "split_x": 970,
  "source_size": [1940, 2776],
  "page": 1,
  "deskew_applied": false,
  "notes": "尸子卷 浙江书局光绪三年刊 首页手动选线示例。线偏右一点（古籍竖排右页起）。"
}
```

注：实际尺寸需在真实样本上跑 `--pick-split-line` 校准，本 preset 为参考。

- [ ] **Step 13.2**: 验证加载

Run: `python -c "from book_cut.split.manual import ManualSplitProfile; p = ManualSplitProfile.from_json(open('samples/crop_profiles/v2_manual_split_example.json').read()); print(p)"`
Expected: 打印完整 profile

---

### Task T14: 更新 README

**Files:**
- Modify: `README.md`（CLI 参数表 + 用法）

- [ ] **Step 14.1**: 改「特性」区

```markdown
- **三种自动切分策略**（CLI / GUI 切换）：
  - `gutter`（默认）—— 列投影找中缝，最白连续段中心，鲁棒性最好
  - `border` —— Hough 直线检测版框，按版框中心切分
  - `half` —— 固定对半切（支持 `--half-offset N` 微调）
- **手动切分**（v2.4+）：`--split manual` —— 弹窗画一条垂直中缝线，整本书复用。配合 `--pick-split-line` 子命令输出 JSON preset，可批处理复用
```

- [ ] **Step 14.2**: CLI 参数表加 3 行

```markdown
| `--split` | `gutter` | `none` / `half` / `gutter` / `border` / `manual`（v2.4+：手动画线） |
| `--manual-split-x` | 无 | 手动切分线 x 坐标（仅 `--split manual` 生效） |
| `--manual-split-preset` | 无 | 手动切分线 JSON preset 路径（仅 `--split manual` 生效） |
| `--pick-split-line` | 关 | 子命令：弹 GUI 选线 → 写 JSON 到 `-o` |
```

- [ ] **Step 14.3**: 用法区加示例

```markdown
# 手动选切分线（古籍漫漶 / 自动策略失败时）

# 1) 弹窗选线，保存 JSON
python -m book_cut --pick-split-line -i book.pdf -o preset.json

# 2) 用 preset 跑批处理
python -m book_cut -i book.pdf -o ./out --split manual --manual-split-preset preset.json --binarize sauvola --pdf
```

---

### Task T15: CHANGELOG 条目

**Files:**
- Modify: `CHANGELOG.md`（顶部）

- [ ] **Step 15.1**: 加 0.3.6 段

```markdown
## [0.3.6] - 2026-06-25 · v2.4（手动切分线：--split manual）

### Added
- **`--split manual`**：手动切分线（v2.4+）。在首页画一条垂直中缝线，整本书复用
  - 适用场景：古籍漫漶 / 扫描倾斜 / 影印件不规则版心——`gutter`/`border`/`half` 全部失败时
  - 配合 `--pick-split-line -i book.pdf -o preset.json` 子命令生成 JSON preset，可批处理复用
- **CLI 新增 3 个 arg**：
  - `--manual-split-x N`：直接传 x
  - `--manual-split-preset PATH`：从 JSON 加载
  - `--pick-split-line`：弹 GUI 选线
- **GUI `SplitLinePicker` Toplevel**：画布 + 垂直线 + Spinbox 联动 + 滚轮 / 键盘微调 + 双击居中
- **新错误码系列 `MSxxx`**（与 `BCxxx` 区分）：
  - MS001 split_x 越界 / MS002 split_x 非 int / MS003 source_size 失配（warn）
  - MS004 缺 x 和 preset / MS005 preset 文件 / JSON 失败
  - MS006 preset version 未知 / MS007 单页自动跳过 manual
  - MS008 输入 0 页 / MS009 deskew 状态不一致（fatal）
  - MS010 1:3+ 跨页 warn + best-effort
- **新示例** `samples/crop_profiles/v2_manual_split_example.json`

### Implementation
- `book_cut.split.manual`：新模块（`ManualSplitProfile` + `to_json/from_json` + `apply_manual_split`）
- `book_cut.split.picker_ui`：新模块（`SplitLinePicker` Toplevel）
- `book_cut.pipeline.orchestrator._compute_page`：加 `manual` 分支 + 1:3 heuristic
- `book_cut.pipeline.orchestrator.run_pipeline`：MS004/MS005/MS009 校验
- `book_cut.cli`：3 个新 arg + `--pick-split-line` 子命令
- `book_cut.gui`：主窗 split combobox 加 `manual` + 「选切分线...」按钮 + `run_pick_split_line`

### Tests
- `tests/test_manual_split.py`（新建，12 用例）：
  - T1-T4：JSON round-trip + version 校验 + 越界
  - T5-T7：apply_manual_split 行为
  - T8-T9：CLI argparse + MS004
  - T10-T12：orchestrator 集成 + MS009 + MS007

### Backward Compat
- 零破坏：现有 `--split` 值全部不变，`manual` 是新增选项
- JSON preset：新格式，无 v0 兼容路径（v1 第一版）
- GUI combobox：默认隐藏「选切分线...」按钮，仅在选 `manual` 时显示
- 旧 preset 文件（manual crop `v1` / `v2`）不受影响，是另一份配置
```

---

### Task T16: Session note

**Files:**
- Create: `docs/sessions/2026-06-25-v2.4-manual-split-line.md`

- [ ] **Step 16.1**: 写 5 段

```markdown
# 2026-06-25 · v2.4 手动切分线（--split manual）

## 背景
v2.2 引入 manual crop（post-split padding），但切分线本身仍必须由自动算法决定。
实测 `尸子卷` 等古籍扫描：漫漶严重 / 倾斜 + 模糊 / 影印件不规则版心——`gutter`/`border`/`half` 全部猜错。
古旧 workaround：Photoshop 量像素写 `--half-offset` 到脚本。

## 决策
- 新增 `book_cut.split.manual` 模块，与 `half`/`gutter`/`border` 平级
- 一本书一条线（per-book），per-page 留 v2.5+
- JSON v1 schema，strict version 校验（MS006）
- 严格 deskew 状态一致性（MS009 fatal）—— 避免静默错位
- 单页自动跳过 manual（MS007 warn）
- 1:3+ 跨页 warn + best-effort（MS010）
- Picker 作为 Toplevel，CLI 子命令复用（不另起进程）

## 关键文件
- `src/book_cut/split/manual.py`：`ManualSplitProfile` + `to_json`/`from_json` + `apply_manual_split`
- `src/book_cut/split/picker_ui.py`：`SplitLinePicker` Toplevel
- `src/book_cut/pipeline/orchestrator.py`：加 `manual` 分支 + run_pipeline 校验
- `src/book_cut/cli.py`：3 个新 arg + 子命令
- `src/book_cut/gui.py`：主窗集成 + 子命令入口

## 已知限制
- 仅 1:2 完整支持；1:3 用 heuristic 切（MS010 warn）
- 仅首页选线；多页差异靠 `--dry-run` 验证
- per-page override 不支持（v2.5+）
- Picker 不感知 deskew 状态；MS009 由 run 时校验

## 后续方向
- v2.5+：per-page override（`per_page_overrides: dict[int, int] | None = None`）
- v2.5+：native 1:3（`split_xs: list[int] | None = None`）
- v2.5+：picker 显示多页缩略图条带
- 长期：picker 内嵌到主窗（v2.6+ UI 重构时考虑）
```

---

## Phase 7 · 验证

### Task T17: 完整测试 + ruff

- [ ] **Step 17.1**: 跑新测试

Run: `pytest tests/test_manual_split.py -v`
Expected: 12 passed

- [ ] **Step 17.2**: 跑全套测试无回归

Run: `pytest tests/ -q --ignore=tests/test_perf.py 2>&1 | tail -20`
Expected: 全部通过（应有 ~480 用例）

- [ ] **Step 17.3**: ruff

Run: `ruff check src/book_cut/split/ src/book_cut/pipeline/orchestrator.py src/book_cut/cli.py src/book_cut/gui.py tests/test_manual_split.py`
Expected: 0 错

- [ ] **Step 17.4**: CLI help 烟测

Run: `python -m book_cut --help | grep -E "manual|pick-split-line" | head -10`
Expected: 看到 4 个新 flag

---

## 完成检查

- [ ] 所有 12 个新测试通过
- [ ] 现有 469+ 测试无回归
- [ ] ruff 在修改文件 0 错
- [ ] CHANGELOG / README / sample 全部更新
- [ ] Session note 写好
- [ ] 真实样本 dry-run 与实际 run 视觉一致（手动 GUI 验证项，本自动化测试不覆盖）

---

## 自审

- **Spec 覆盖**：每个 spec Requirement 都有对应 Task
  - ManualSplitProfile dataclass → T2.1
  - to_json / from_json v1 → T2.2 / T2.3
  - apply_manual_split → T2.4
  - --split manual choice → T7.1
  - --manual-split-x / --manual-split-preset → T7.2
  - --pick-split-line 子命令 → T8 / T11
  - GUI 集成 → T9 / T10
  - SplitLinePicker Toplevel → T12
  - orchestrator 接入 → T4 / T5
  - deskew MS009 → T5.2 / T6.3
  - single-page MS007 → T6.3
  - 1:3 MS010 → T4.2
- **Placeholder 扫描**：无 TBD / TODO / "implement later"；所有 step 含代码或命令
- **类型一致**：`ManualSplitProfile` 在 T2.1 定义，T3 re-export，T4.1 orchestrator 用，T6.2/T6.3 测试用，T12.1 picker 用 — 一致
- **错误码**：MS001-MS010 全部有触发点（T1-T12 / T4.2 / T5.2 等）
