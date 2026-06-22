"""古籍双页切分工具。"""

import os

# OpenSSL 3.0 legacy provider 兼容性 fix
# 背景:Homebrew openssl@3 把 legacy provider 拆为独立 formula,未装时
# cryptography 库在 import 阶段会 fatal("OpenSSL 3.0's legacy provider failed to load")。
# pypdf 内部会 import cryptography(用于 PDF 加密/证书),所以只要开了 --pdf 输出
# (走 pypdf.PdfReader/PdfWriter 路径)就会触发。
# 官方推荐:设置 CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1 即可禁用 legacy 算法检查。
# 必须在 import cryptography/pypdf 之前,所以放在 book_cut 包入口(__init__.py)。
# setdefault 不会覆盖用户已设的环境变量。
os.environ.setdefault("CRYPTOGRAPHY_OPENSSL_NO_LEGACY", "1")

__version__ = "0.1.7"
