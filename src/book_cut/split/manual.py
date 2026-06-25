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
