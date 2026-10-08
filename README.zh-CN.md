# Project Radar

[English](./README.md) | **简体中文**

扫描一个公开 GitHub 仓库,得到**最值得构建的 Top 3 问题**——有排序、有证据、有解释。

Project Radar 采集 issue、Pull Request 和 Discussion,把它们聚合成反复出现的问题,用**类型化判断**(通过 [Jev / TypeSafe API](https://typesafe.ai),无 key 时回退到确定性启发式判断)逐组裁决,再由透明的评分引擎打分。每条结论都回链到支撑它的具体 issue 和 PR。

## 工作原理

```
GitHub ──▶ 采集 ──▶ 规范化/去重 ──▶ 聚类 ──▶ 判定 (Jev) ──▶ 排序 ──▶ 报告
 issues   评论        bot/重复         TF-IDF    5 个类型化      加权     Top 3 +
 pulls     timeline    过滤             + 重叠    问题           证据链    全部候选
 discussions                                                    候选
```

1. **采集** — issue(open + 回溯窗口内的 closed)、PR、评论、issue timeline,以及 GraphQL Discussions(需 token)。全程预算感知:每个请求都计入 GitHub 速率配额,超限时优雅降级而不是直接失败。
2. **规范化** — issue/PR/discussion 统一为一套 artifact 结构,过滤 bot 与重复,附加评论内容。
3. **聚类** — TF-IDF 相似度(标题加权 ×2)叠加 token 重叠矩阵(捕捉换言复述的报告)。对单链连通分量先剪掉弱连接成员,再对超大簇二次切分,确保一堆互不相关的问题永远不会被粘成一个"问题"。
4. **判定** — 每个候选簇由 Jev 回答五个类型化问题:`same_problem`、`recurring_independent`、`still_unresolved`(noul)、`worth_building`(score)、`problem_type`(choice)。没有 `TYPESAFE_API_KEY` 时,同构 schema 的确定性启发式判定器接管 —— 输出结构一致,零网络。
5. **排序** — 确定性评分引擎(不依赖第二个 LLM):

   | 信号 | 权重 |
   |---|---|
   | recurrence(反复出现) | 0.25 |
   | unresolved(未解决) | 0.25 |
   | user_demand(用户需求) | 0.20 |
   | buildability(可构建性) | 0.15 |
   | cross_surface(跨载体) | 0.15 |

   历史 confirm/reject 反馈按标题调整优先级,雷达按仓库持续学习。

**设计准则:** 模型只输出类型化判断。计数、打分、排序、证据组装全部是确定性代码 —— 同一仓库扫两次,数字一致。

## 快速开始

### 本地运行

```bash
pip install -r requirements.txt
cp .env.example .env            # 可选:填入 GITHUB_TOKEN / TYPESAFE_API_KEY
uvicorn backend.app.main:app --reload
```

打开 http://127.0.0.1:8000 —— UI 与后端同进程提供。

### Docker

```bash
docker compose up --build
```

## 配置

全部通过环境变量驱动(见 `.env.example`):

| 变量 | 默认值 | 用途 |
|---|---|---|
| `GITHUB_TOKEN` | — | 速率 60 → 5000/时;启用 Discussions(GraphQL) |
| `TYPESAFE_API_KEY` | — | Jev 判定;缺省时使用启发式判定 |
| `JEV_MODEL` | `jev-latest` | Jev 模型 id |
| `EMBEDDING_BACKEND` | `tfidf` | `tfidf`(零下载)或 `sentence-transformers` |
| `SCAN_LOOKBACK_DAYS` | `365` | 参与扫描的 closed 时间窗 |
| `MAX_ISSUES` / `MAX_PRS` / `MAX_DISCUSSIONS` | `400` / `200` / `100` | 采集上限 |
| `MAX_COMMENT_FETCHES` | `300` | 评论补全上限 |
| `MAX_TIMELINE_FETCHES` / `MAX_PULL_DETAILS` | `12` / `8` | 修复证据增强上限 |
| `GITHUB_MIN_BUDGET` | `20` | 低于该配额预留则跳过证据增强 |
| `DATA_DIR` | `./data` | SQLite 数据库 + 每仓库上下文文件 |

密钥只在后端读取,绝不下发到浏览器。

## API

| 方法与路径 | 用途 |
|---|---|
| `POST /api/scans` | 启动扫描(`{"repo": "owner/name"}`),返回 `scan_id` |
| `GET /api/scans/{id}` | 进度(阶段、百分比、标签) |
| `GET /api/scans/{id}/report` | Top 3 问题 + 全部候选 + 证据链 |
| `GET /api/candidates/{id}` | 该次扫描的全部候选 |
| `GET /api/problems/{id}` | 单个问题及其 artifacts |
| `POST /api/problems/{id}/feedback` | `confirm` / `reject` / `split` / `solved` / `minor` |
| `GET /api/repos` · `GET /api/repos/{owner}/{name}/context` | 已扫描仓库 + 学到的上下文 |
| `POST /api/repos/{owner}/{name}/context/non_goals` | 记录非目标 |
| `GET /api/health` | 存活检查 |

## 报告格式

Top 3 的每个问题都用证据回答四个问题:

- **为什么存在** —— 多少独立作者、跨多长时间、出现在几个载体上
- **为什么未解决** —— 失效的修复尝试、长期开放的 issue、未解决概率
- **为什么值得构建** —— `worth_building` 分数、需求信号、维护者信号
- **最小修复** —— 由问题类型推导的具体第一步

外加一条按时间排序的**证据链**,链接到每个来源 issue/PR/discussion。

## 开发

```bash
pip install -r requirements.txt
python -m pytest backend/tests -q     # 65 个测试,无需网络
```

测试强制 `EMBEDDING_BACKEND=tfidf` 并使用伪造 GitHub 客户端,CI 无需任何 token。

```
backend/app/
  github/        REST + GraphQL 采集器,速率预算
  ingest/        规范化、去重/噪声过滤
  clustering/    TF-IDF + 重叠图,剪枝/切分组装
  judge/         Jev 客户端、类型化问题定义、启发式回退
  ranking/       证据抽取、确定性评分
  memory/        每仓库上下文、反馈学习
  db/            SQLite schema 与辅助函数
  pipeline.py    编排
  main.py        FastAPI 应用
frontend/        零构建原生 JS UI
```

## 许可证

MIT —— 见 [LICENSE](LICENSE)。
