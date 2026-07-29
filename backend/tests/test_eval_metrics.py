from app.eval import metrics as M


def test_recall_at_k():
    assert M.recall_at_k([1, 2, 3], {2, 4}, k=5) == 0.5  # 命中 {2}，相关 {2,4}
    assert M.recall_at_k([1, 3, 5], {2, 4}, k=5) == 0.0
    assert M.recall_at_k([1, 2], {1, 2}, k=1) == 0.5  # 只看 top1


def test_mrr():
    assert M.mrr([3, 2, 1], {1}) == 1 / 3
    assert M.mrr([1, 2], {1}) == 1.0
    assert M.mrr([5, 6], {1}) == 0.0


def test_ndcg_perfect_and_partial():
    rel = {1, 2}
    assert M.ndcg([1, 2], rel, k=5) == 1.0          # 完美排序
    assert 0.0 < M.ndcg([3, 1], rel, k=5) < 1.0     # 部分命中
    assert M.ndcg([9, 8], rel, k=5) == 0.0


def test_citation_accuracy():
    assert M.citation_accuracy([1, 2], {1, 3}) == 0.5
    assert M.citation_accuracy([], {1}) == 0.0
    assert M.citation_accuracy([1, 2], {3, 4}) == 0.0


def test_bbox_iou_and_accuracy():
    a = [0.1, 0.1, 0.5, 0.5]
    assert M.bbox_iou(a, a) == 1.0
    assert M.bbox_iou(a, [0.4, 0.4, 0.6, 0.6]) > 0.0
    assert M.bbox_iou(a, [0.9, 0.9, 1.0, 1.0]) == 0.0
    assert M.bbox_accuracy(a, a) == 1.0
    assert M.bbox_accuracy(a, None) == 0.0


def test_aggregate():
    per = [{"recall@4": 0.5, "mrr": 1.0}, {"recall@4": 1.0, "mrr": 0.5}]
    agg = M.aggregate(per, ["recall@4", "mrr"])
    assert agg["recall@4"] == 0.75
    assert agg["mrr"] == 0.75
    assert agg["n_cases"] == 2


# ===== 生成层指标（plan_four §2） =====
def test_token_overlap():
    gold = "工龄 满一年 五天 满五年 十天"
    assert M.token_overlap("工龄 满一年 五天", gold) == 1.0   # 答案词全在金标
    assert 0.0 < M.token_overlap("工龄 五天 其他 词", gold) < 1.0
    assert M.token_overlap("完全 无关 的 内容", gold) == 0.0
    assert M.token_overlap("", gold) == 0.0


def test_faithfulness_grounded_and_hallucinated():
    ctx = ["住宿 标准 一线 城市 每晚 六百 元"]
    # 答案完全来自上下文 → 1.0
    assert M.faithfulness("住宿 一线 城市 每晚 六百", ctx) == 1.0
    # 答案引入上下文之外的词 → < 1.0
    assert 0.0 < M.faithfulness("住宿 每晚 六百 虚构 数据", ctx) < 1.0
    # 完全幻觉 → 0.0
    assert M.faithfulness("虚构 数据 无中生有", ctx) == 0.0
    # 空答案 / 空上下文
    assert M.faithfulness("", ctx) == 0.0
    assert M.faithfulness("住宿 六百", []) == 0.0


def test_faithfulness_bigram_stricter():
    ctx = ["禁止 硬编码 密钥 代码 仓库"]
    # unigram 命中，但 bigram 顺序不同 → bigram 更低
    uni = M.faithfulness("硬编码 密钥 仓库 代码", ctx, n=1)
    bi = M.faithfulness("硬编码 密钥 仓库 代码", ctx, n=2)
    assert uni == 1.0
    assert 0.0 <= bi < uni
