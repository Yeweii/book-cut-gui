"""preprocess 子包：二值化、倾斜校正、图像增强等预处理。

v1.9+：新增 ``preprocess(image, chain, quality)`` dispatcher，支持链式应用
sharpen / denoise / clahe / gamma 4 个增强 op（每个 fast/balanced/best 三档）。

流水线位置：deskew **之前**，原始 PIL.Image 上做（不破坏 A1 单次 RGB→L）。
"""

from __future__ import annotations

from PIL import Image

from book_cut.preprocess.clahe import clahe, clahe_chain_token
from book_cut.preprocess.denoise import denoise, denoise_chain_token
from book_cut.preprocess.gamma import gamma, gamma_chain_token
from book_cut.preprocess.sharpen import sharpen, sharpen_chain_token

_OP_TOKEN_PARSERS = {
    # name: (callable, tokenizer)
    "sharpen": (sharpen, sharpen_chain_token),
    "sharp": (sharpen, sharpen_chain_token),
    "denoise": (denoise, denoise_chain_token),
    "dn": (denoise, denoise_chain_token),
    "clahe": (clahe, clahe_chain_token),
    "cl": (clahe, clahe_chain_token),
    "gamma": (gamma, gamma_chain_token),
    "gm": (gamma, gamma_chain_token),
}


def parse_chain(chain_str: str) -> list[str]:
    """解析 ``--preprocess`` 字符串 → token list。

    规则：逗号分隔，strip 空白，丢空串。

    >>> parse_chain("sharpen,denoise=10, clahe = 2.5")
    ['sharpen', 'denoise=10', 'clahe = 2.5']
    """
    return [t.strip() for t in chain_str.split(",") if t.strip()]


def preprocess(
    image: Image.Image,
    chain: list[str] | str,
    quality: str = "balanced",
) -> Image.Image:
    """v1.9+ 流水线预处理 dispatcher。

    按 ``chain`` 顺序应用每个 op（前一个的输出是后一个的输入）。

    Args:
        image: 输入图像（任意模式；op 内部按需 ``convert("L")``）。
        chain: op token list（如 ``["sharpen", "denoise=10", "clahe=2.0"]``）
               或逗号分隔字符串（与 ``--preprocess`` 兼容）。
        quality: fast / balanced / best。``balanced`` 默认。

    Returns:
        处理后的 Image（mode 由各 op 决定；当前所有 op 内部统一转 L）。

    Raises:
        ValueError: 未知 op token / gamma 越界。
    """
    if isinstance(chain, str):
        chain = parse_chain(chain)
    if not chain:
        return image

    q = quality.lower()
    if q not in ("fast", "balanced", "best"):
        raise ValueError(f"未知 preprocess quality: {quality!r}（合法: fast/balanced/best）")

    out = image
    for token in chain:
        # 用 token 的 key 部分查表（支持 "sharpen=2.0" → "sharpen"）
        key = token.split("=", 1)[0].strip().lower()
        if key not in _OP_TOKEN_PARSERS:
            raise ValueError(
                f"未知 preprocess op: {key!r}（合法: sharpen/denoise/clahe/gamma）"
            )
        op_func, token_parser = _OP_TOKEN_PARSERS[key]
        _, val = token_parser(token)
        # 把显式数值传给对应 op；None → op 用 quality 默认
        if key in ("sharpen", "sharp"):
            out = op_func(out, amount=val, quality=q)
        elif key in ("denoise", "dn"):
            out = op_func(out, h=int(val) if val is not None else None, quality=q)
        elif key in ("clahe", "cl"):
            out = op_func(out, clip=val, quality=q)
        elif key in ("gamma", "gm"):
            out = op_func(out, value=val, quality=q)
    return out


__all__ = [
    "preprocess",
    "parse_chain",
    "sharpen",
    "denoise",
    "clahe",
    "gamma",
]
