# 提交说明：素材检索与结果导出

- **Fork**：https://github.com/yswang24/AI-Engineer-Quiz
- **基线**：`3aa137ccde6f981981582f6f71b81448c72a9dab`（收到题目时的 `main`）
- **开发分支**：`feat/combined-filter-sort-export`
- **最终 commit SHA**：以本仓库该分支 HEAD 及提交邮件为准（文档提交之后仍在同一个分支上，未 squash / amend / rebase）。

## 1. 运行与验证

需要 Python 3.10+；前端纯函数测试需要 Node（缺失时自动 skip）。本次在本地 Python 3.12 下完成。仓库根目录执行：

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

页面操作步骤：登录 → 在搜索框输入 `harbor` → 集合选 `Campaigns` → 包含标签填 `approved, campaign` → 排除标签填 `internal` → 点 **Apply** → 排序选 **Created: oldest** → 用 **Previous / Next** 翻页 → 点 **Export CSV (all matches)** 下载。生效条件以 chip 形式显示，点 chip 或 **Clear all** 可移除条件；条件也会同步到 URL，刷新或分享链接可还原视图。侧栏 Media type 仍可用，且会传入导出。

## 2. 代码、测试与数据生成方式

| 文件 | 内容 |
| --- | --- |
| `keepstack/search.py` | 组合筛选条件构造、确定性排序、计数、分块取行、标签批量查询 |
| `keepstack/export.py` | 流式 CSV 序列化（UTF-8 BOM、逗号/引号/换行转义、公式中和） |
| `keepstack/app.py` | `/api/assets` 扩展参数与严格校验、`/api/assets/export.csv`、导出审计 |
| `keepstack/db.py` | 标签反查、大小写无关标签名、创建时间排序的表达式索引 |
| `web/index.html`、`web/app.js`、`web/styles.css` | 零构建前端：筛选面板、条件 chip、分页、卡片标签、URL 同步、导出与错误态 |
| `web/filters.js` | 无 DOM 依赖的筛选纯函数（拆分标签、构造 query、解析 URL） |
| `scripts/generate_fixture.py` | 13 条确定性素材 + 2 个集合，含同 instant 不同时区后缀、删除状态、大小写标签、中文/逗号/引号/换行字段 |
| `tests/test_filters_export.py` | 组合筛选、多页与同时间戳、分块一致性、导出与审计、特殊字符、修改后查询等 |
| `tests/test_web_filters.mjs`、`tests/test_web_helpers.py`、`tests/test_zz_config_restored.py` | 前端纯函数 Node 测试、pytest 包装、测试隔离回归 |

数据脚本不依赖二进制素材：每个素材写一条最小 JPEG blob 和直接插入的目录行；重复运行会先删除并重建 `fixture-*` 行，不影响库内其他数据。脚本输出 Campaigns 集合 id 和预期组合筛选结果：8 条，oldest 顺序为

`fixture-009, fixture-013, fixture-011, fixture-008, fixture-004, fixture-001, fixture-003, fixture-010`。

其中 `fixture-001 / 003 / 010` 是同一 instant（分别用 `Z` 与 `+00:00` 后缀），用于验证 `julianday()` + `id` 的稳定排序；`fixture-002 / 006` 带 `internal`，`fixture-005` 缺少 `campaign`，`fixture-007` 已删除，`fixture-012` 缺少 `approved`，均应被排除。

## 3. 实测结果

- `python -m pytest -q`：**33 passed, 2 skipped**（2 个 skip 是上游依赖可选模型/tesseract 的既有测试）。仅有上游 FastAPI `on_event` / TestClient 的弃用警告。
- HTTP 冒烟（本地 uvicorn + 上述筛选）：`total=8`，`limit=3&offset=0` 返回 `fixture-009, fixture-013, fixture-011`；导出接口返回 8 行 + 表头，UTF-8 BOM 与中文均正常。
- CSV 字段用 `csv.DictReader` 回读后与列表页全部结果的 uuid 顺序一致；含逗号、双引号、换行的字段逐字还原；零结果仍只有表头；未登录请求返回 401。
- 导出写成 `asset.export` 审计记录，detail 含条数与筛选摘要；以 `=` 开头的标题导出为 `'=...`，不再被表格当公式。
- 非法参数（非 active 的 `status`、未知 `sort` / `mode`、semantic 带组合筛选）返回 400；纯标点关键词按“无关键词限制”处理，不再 500。
- 修改标题/描述或增删标签后，下一次查询与导出立即反映修改（测试覆盖）。

## 4. 主要取舍

- **用 EXISTS 子查询而非多表 JOIN** 表达多标签条件：避免一个素材因多个匹配标签被重复计数，也不需要 `DISTINCT` 破坏排序。同一标签同时出现在包含/排除中自然得到空集。
- **所有排序追加 `a.id` 作为唯一 tie-breaker**，创建时间排序用 `julianday()` 并配表达式索引：兼容 `Z` 与 `+00:00`，同 instant 也不跨页重复/遗漏。修复了原实现有关键词时强制按 `bm25` 排序的问题；关键词仍沿用原 FTS 字段和 porter unicode61 分词。
- **列表与导出共用 `fetch_rows` / `iter_rows` 和同一套查询参数**：导出按批次取行、逐行 `StreamingResponse` 输出，标签查询也分块，既导出全部匹配结果，又不会把大数据集整体读入内存。
- **CSV 带 UTF-8 BOM**，标签以 `; ` 连接并按名称排序；以 `= + - @` 开头的字段加 `'` 前缀中和表格公式，代价是这类单元格不再自动求值。
- **API 不再静默忽略参数**：不受支持的 status / sort / mode / semantic+组合筛选直接 400，避免调用方误以为条件已生效。
- **前端保持零构建**：纯函数抽到 `web/filters.js` 用 Node 测；递增请求序号丢弃过期响应；筛选条件通过 `replaceState` 同步到 URL；卡片展示标签便于人工核对命中原因。
- **导出写审计日志**，与上游其余 mutation 的审计口径一致；侧栏统计维持全局口径并标注 `(all assets)`。

## 5. 限制与未完成项

- 题目要求的组合筛选、排序分页、CSV 导出、修改后结果正确性均已完成，**无未完成项**。
- 语义搜索是上游遗留能力，接口仍可调用但从页面隐藏；带组合筛选时返回 400（题目只验收关键词搜索）。
- 列表和导出不跨请求做快照；若在两次请求之间数据发生变化，结果可能不同（题目明确不要求跨请求快照）。
- 公式中和会改变以 `= + - @` 开头字段的字面值（加一个 `'` 前缀）；这是为防止表格软件执行不可信元数据做的取舍。
- 标签输入按逗号（含中文逗号）分隔并统一转小写，因此名称本身包含逗号的标签无法通过输入表达。
- 前端交互（chip 点击、分页按钮、导出下载）目前是纯函数测试 + 源码契约检查，未接入真实浏览器自动化；Node 缺失时纯函数测试会跳过。
- URL 用 `replaceState`，不会在浏览器历史里留下每一步筛选；这是为了避免“返回”按钮逐条回退筛选状态。
