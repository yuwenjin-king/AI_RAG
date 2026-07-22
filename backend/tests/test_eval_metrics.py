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
