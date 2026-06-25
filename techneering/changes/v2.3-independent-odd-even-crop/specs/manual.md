# Spec: v2.3 手动裁切独立奇偶页

## 数据结构

```python
@dataclass(frozen=True)
class PageCropProfile:
    top: int
    bottom: int
    inner: int
    outer: int

@dataclass(frozen=True)
class ManualCropProfile:
    odd_page: PageCropProfile
    even_page: PageCropProfile
    source_size: tuple[int, int] | None = None
    notes: str = ""
```

## JSON Schema

### v2（推荐，新格式）
```json
{
  "version": 2,
  "odd_page":  {"top": 50, "bottom": 40, "inner": 80, "outer": 30},
  "even_page": {"top": 50, "bottom": 40, "inner": 30, "outer": 80},
  "source_size": [4947, 7610],
  "notes": "..."
}
```

### v1（兼容，自动迁移）
```json
{
  "version": 1,
  "top": 50, "bottom": 40, "inner": 80, "outer": 30,
  "mirror_even": true,
  "source_size": [4947, 7610],
  "notes": "..."
}
```
- `mirror_even=True`  → even_page = {T, B, outer, inner}（镜像）
- `mirror_even=False` → even_page = {T, B, inner, outer}（同 odd）

迁移在 `from_json` 内存中完成，旧文件不动；`to_json` 始终输出 v2。

## apply_manual_crop

```python
def apply_manual_crop(arr, profile, is_even):
    p = profile.even_page if is_even else profile.odd_page
    h, w = arr.shape[:2]
    return arr[p.top : h - p.bottom, p.inner : w - p.outer]
```

边界检查（top+bottom>=h 或 inner+outer>=w）抛 ValueError，行为同 v2.2。

## CLI

- `--manual-odd-padding "T,B,I,O"`：奇页 padding（保留）
- `--manual-even-padding "T,B,I,O"`：偶页 padding（新增，可选）
- `--manual-mirror-even`：保留但 warn 已忽略（废弃）
- 不指定 even 时：默认从 odd 镜像生成（mirror_even=True 行为）

## GUI

Manual Crop 面板：
- 奇页组：T/B/I/O Spinbox + "📐 拖奇页框" 按钮
- 偶页组：T/B/I/O Spinbox + "📐 拖偶页框" 按钮
- 删除原"偶页镜像"checkbox（或保留并灰化）
- Load/Save preset 升级到 v2 JSON