# 评估指南（plan_four §2）

平台内置一套**可回归、可复现**的检索/引用/溯源/生成评估框架（设计书 §9），用于回答
"RAG 到底有没有把对的东西召回来、答对、引对位置"。

## 组件

| 文件 | 作用 |
|---|---|
| `backend/app/eval/metrics.py` | 纯函数指标：Recall@K / MRR / NDCG / 引用准确率 / bbox IoU+命中率 / faithfulness / token_overlap |
| `backend/app/eval/corpus.py` | 确定性评估语料（~10 文档 × 多段落 + ~15 用例，覆盖文本/表格/bbox/多关键词/无答案） |
| `backend/app/eval/seed.py` | 装载器：`seed_eval_corpus()` 建 KB+场景+文档+chunk+用例（幂等）；CLI `python -m app.eval.seed` |
| `backend/app/eval/runner.py` | `run_eval()` 批量检索 → 算指标 → 聚合；可选 `generate` 回调跑生成层 faithfulness |
| `backend/app/eval/__main__.py` | CLI `python -m app.eval [--with-generation]` |

## 指标

- **检索层**：Recall@K（期望文档是否进入 Top-K）、MRR、NDCG、引用准确率（cited ∩ relevant / cited）。
- **溯源层**：bbox_accuracy（预测区域与真值 IoU ≥ 0.5 记命中）——评估"引用指到的位置对不对"。
- **生成层**（`--with-generation` 或传 `generate`）：faithfulness（答案 n-gram 被检索上下文覆盖比例，低幻觉）、
  answer_overlap（答案与金标重叠）。无 LLM key 时为规则近似；真实质量评估叠加 LLM judge。

## 用法

### 离线回归门禁（开发/CI，无需真实 infra）
```bash
cd backend && python -m pytest tests/test_eval_corpus.py -q
```
seed 语料入 sqlite → `run_eval`（BM25 本地兜底 + mock generate）→ 断言召回/bbox/faithfulness 高于基线。
**作用**：守住 chunking→检索→指标→溯源→生成链路不回归。

### 真实环境评估（plan_four §3，需全套 infra）
```bash
make up && make migrate
make eval-seed TENANT=default SCENE=eval          # 装载语料（幂等；RESET=1 重建）
make eval TENANT=default SCENE=eval               # 检索层指标
make eval TENANT=default SCENE=eval GEN=1         # 追加生成层 faithfulness（需 LLM_API_KEY）
```
真实环境跑的是**混合检索**（向量 + OpenSearch BM25 + RRF + rerank），所得为真实效果数；
`--with-generation` 配合 `LLM_API_KEY` 时 faithfulness 基于真实生成答案。

## 诚实边界

- 离线语料以**空格分词**（离线 BM25 用 `split()`，中文无空格无法召回）；真实 OpenSearch 用 CJK 分析器，
  可加载自然文本。语料**结构**（文档/段落/page_no/bbox/用例）对二者通用。
- 离线 faithfulness 为规则近似（n-gram 覆盖），真实质量评估应叠加 LLM judge（§3）。
- 评估集目前为合成语料；生产可替换 `corpus.py` 为真实业务文档 + 标注用例（同结构）。
