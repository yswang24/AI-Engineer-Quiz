# 提交说明：素材检索与结果导出

- **Fork**：https://github.com/yswang24/AI-Engineer-Quiz
- **基线**：`3aa137ccde6f981981582f6f71b81448c72a9dab`（收到题目时的 `main`）
- **开发分支**：`feat/combined-filter-sort-export`
- **最终 commit SHA**：以本仓库该分支 HEAD 及提交邮件为准（文档提交之后仍在同一个分支上，未 squash / amend / rebase）。

## 1. 运行与验证

需要 Python 3.10+。本次在本地 Python 3.12 下完成。仓库根目录执行：

```bash
uv venv --clear --seed --python 3.12
uv pip install 'fastapi>=0.115' 'uvicorn>=0.30' 'python-multipart>=0.0.9' \
              'Pillow>=10' 'pytest>=8' 'httpx>=0.27'

export KEEPSTACK_AI_ENABLED=false
export KEEPSTACK_OCR_ENABLED=false

# 自动化测试（无需先启动服务）
uv run --no-sync python -m pytest -q

# 生成可复现的演示数据（只重建 uuid 前缀为 fixture- 的数据）
uv run --no-sync python scripts/generate_fixture.py --data-dir /tmp/keepstack-quiz-fixture

# 启动服务
KEEPSTACK_DATA_DIR=/tmp/keepstack-quiz-fixture \
  uv run --no-sync python -m uvicorn keepstack.app:app --host 127.0.0.1 --port 8000
```

打开 <http://localhost:8000>，账号 `admin` / `admin`。未设置 `KEEPSTACK_DATA_DIR` 时脚本使用仓库内的 `data/`，该目录已被 `.gitignore` 排除，不随提交发布。

> 本机的 uv 可编辑安装（`uv pip install -e '.[dev]'`）在含中文的绝对路径下触发 setuptools `EEXIST` 构建错误，因此上面改为显式安装运行/测试依赖，并从仓库根目录运行（Python 自动把当前目录加入 `sys.path`）。应用代码本身未依赖可编辑安装。

页面操作步骤：登录 → 在搜索框输入 `harbor` → 集合选 `Campaigns` → 包含标签填 `approved, campaign` → 排除标签填 `internal` → 点 **Apply** → 排序选 **Created: oldest** → 用 **Previous / Next** 翻页 → 点 **Export CSV (all matches)** 下载。生效条件以 chip 形式显示，点 chip 或 **Clear all** 可移除条件。侧栏 Media type 仍可用，且会传入导出。

## 2. 代码、测试与数据生成方式

| 文件 | 内容 |
| --- | --- |
| `keepstack/search.py` | 组合筛选条件构造、确定性排序、列表/导出共用的 `fetch_rows` |
| `keepstack/export.py` | CSV 序列化（UTF-8 BOM、`csv.writer`、标签字段） |
| `keepstack/app.py` | `/api/assets` 扩展参数、`/api/assets/export.csv` 导出接口、分页参数校验 |
| `web/index.html`、`web/app.js`、`web/styles.css` | 零构建前端：筛选面板、条件 chip、排序/分页、导出与错误处理 |
| `scripts/generate_fixture.py` | 13 条确定性素材 + 2 个集合，含同时间戳、删除状态、大小写标签、中文/逗号/引号/换行字段 |
| `tests/test_filters_export.py` | 组合筛选、多页与同时间戳、导出一致性、特殊字符、修改后查询等 4 组测试 |

数据脚本不依赖二进制素材：每个素材写一条最小 JPEG blob 和直接插入的目录行；重复运行会先删除并重建 `fixture-*` 行，不影响库内其他数据。脚本输出 Campaigns 集合 id 和预期组合筛选结果：8 条，oldest 顺序为

`fixture-009, fixture-013, fixture-011, fixture-008, fixture-004, fixture-001, fixture-003, fixture-010`。

其中 `fixture-001 / 003 / 010` 创建时间完全相同，用于验证同时间戳下的分页稳定性；`fixture-002 / 006` 带 `internal`，`fixture-005` 缺少 `campaign`，`fixture-007` 已删除，`fixture-012` 缺少 `approved`，均应被排除。

## 3. 实测结果

- `python -m pytest -q`：**26 passed, 2 skipped**（2 个 skip 是上游依赖可选模型/tesseract 的既有测试）。仅有上游 FastAPI `on_event` / TestClient 的弃用警告。
- HTTP 冒烟（本地 uvicorn + 上述筛选）：`total=8`，`limit=3&offset=0` 返回 `fixture-009, fixture-013, fixture-011`；导出接口返回 8 行 + 表头，UTF-8 BOM 与中文均正常。
- CSV 字段用 `csv.DictReader` 回读后与列表页全部结果的 uuid 顺序一致；含逗号、双引号、换行的字段逐字还原；零结果仍只有表头；未登录请求返回 401。
- 修改标题/描述或增删标签后，下一次查询与导出立即反映修改（测试覆盖）。

## 4. 主要取舍

- **用 EXISTS 子查询而非多表 JOIN** 表达多标签条件：避免一个素材因多个匹配标签被重复计数，也不需要 `DISTINCT` 破坏排序。同一标签同时出现在包含/排除中自然得到空集。
- **所有排序追加 `a.id` 作为唯一 tie-breaker**：修复原实现在有关键词时强制按 `bm25` 排序、且同创建时间可能跨页重复/遗漏的问题。关键词仍沿用原 FTS 字段和 porter unicode61 分词。
- **列表与导出共用 `fetch_rows` 和同一套查询参数**：导出不传 `LIMIT/OFFSET`，因此天然导出全部匹配结果，不会受当前页影响。
- **CSV 带 UTF-8 BOM**：面向内容运营常用表格软件，保证中文直接打开不乱码；标签以 `; ` 连接并按名称排序。
- **前端保持零构建**：只新增原生 JS 状态与 DOM；用递增请求序号丢弃过期响应，避免快速切换条件时旧结果覆盖新结果。导出走带 Bearer token 的 `fetch` + Blob 下载，因为普通链接无法携带现有鉴权头。
- **侧栏统计维持全局口径**，标题明确写 `(all assets)`，不冒充当前筛选结果数（题目允许不联动）。

## 5. 限制与未完成项

- 题目要求的组合筛选、排序分页、CSV 导出、修改后结果正确性均已完成，**无未完成项**。
- 语义搜索是上游遗留能力，接口仍可调用但从页面隐藏；它不参与组合筛选（题目只验收关键词搜索）。
- 列表和导出不跨请求做快照；若在两次请求之间数据发生变化，结果可能不同（题目明确不要求跨请求快照）。
- CSV 不中和以 `=` / `+` / `-` / `@` 开头的表格公式；字段值按原文导出，打开不可信元数据时需由使用者自行注意。
- 标签输入按逗号（含中文逗号）分隔并统一转小写，因此名称本身包含逗号的标签无法通过文本框表达；API 的重复参数也只能表达不含逗号的标签名。
- 导出一次性把全部匹配行读入内存并生成字符串；演示数据量（13 条）足够，超大数据集应改为流式导出。
