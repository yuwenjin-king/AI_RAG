"""确定性评估语料集（plan_four §2）。

目的：给"真实 RAG 效果"提供一个**可回归、可复现**的评估集——seed 入库后由
`run_eval` 跑检索/引用/溯源/生成指标，构成回归门禁。

设计取舍（诚实边界）：
- 离线 BM25 兜底用 `content.split()` 空白分词（见 retrieval/keyword.py），中文无空格
  会整段成一个 token 无法召回。故本语料**以空格分隔词/短语**，保证离线确定性召回。
- 真实效果数（OpenSearch CJK 分析器 + 真实 embedding 混合检索）由 plan_four §3
  在真实环境跑；本语料的**结构**（文档/段落/page_no/bbox/case）对二者通用。
- 覆盖：普通文本召回、表格内容召回、bbox 溯源、多关键词、跨文档、无答案。

每文档拆为若干 passage（=chunk），部分 passage 带 page_no + bbox 以评估区域级溯源。
case.expected_docs 用文档 slug，seed 时解析为真实 doc_id。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class CorpusPassage:
    text: str
    page_no: Optional[int] = None
    bbox: Optional[List[float]] = None  # 归一化 [x0, y0, x1, y1]


@dataclass(frozen=True)
class CorpusDoc:
    slug: str
    title: str
    passages: List[CorpusPassage]


@dataclass(frozen=True)
class CorpusCase:
    slug: str
    query: str
    expected_docs: List[str]                # 文档 slug（seed 时解析为 id）
    expected_page: Optional[int] = None
    expected_bbox: Optional[List[float]] = None
    gold_answer: Optional[str] = None
    tags: List[str] = field(default_factory=list)


# ===== 语料文档（空格分词；~10 篇） =====
CORPUS_DOCS: List[CorpusDoc] = [
    CorpusDoc(
        slug="travel_policy",
        title="差旅报销管理制度",
        passages=[
            CorpusPassage(
                "差旅 报销 制度 员工 出差 交通 住宿 餐饮 发票 流程 审批 "
                "出差 前 须 提交 申请 经 主管 审批 出差 后 五个 工作 日 内 报销",
                page_no=1,
            ),
            CorpusPassage(
                "交通 工具 标准 飞机 经济 舱 高铁 二等座 出差 距离 超过 八百 公里 可 飞机",
                page_no=2,
            ),
            CorpusPassage(
                "住宿 标准 北京 上海 深圳 每晚 六百 元 其他 城市 每晚 四百 五十 元",
                page_no=3, bbox=[0.08, 0.40, 0.92, 0.55],
            ),
        ],
    ),
    CorpusDoc(
        slug="leave_policy",
        title="年假与休假管理办法",
        passages=[
            CorpusPassage(
                "年假 休假 管理 员工 工龄 满 一年 享有 年假 五天 工龄 满 五年 年假 十天",
                page_no=1,
            ),
            CorpusPassage(
                "请假 流程 系统 提交 主管 审批 紧急 情况 电话 报备 事后 补单",
                page_no=2, bbox=[0.10, 0.30, 0.90, 0.45],
            ),
        ],
    ),
    CorpusDoc(
        slug="ops_runbook",
        title="生产服务器运维手册",
        passages=[
            CorpusPassage(
                "服务器 运维 手册 生产 故障 告警 响应 时间 五分钟 处理 时限 三十 分钟",
                page_no=1,
            ),
            CorpusPassage(
                "发布 窗口 每周 二 四 低峰 时段 禁止 周五 发布 变更 须 回滚 预案",
                page_no=4,
            ),
        ],
    ),
    CorpusDoc(
        slug="security_policy",
        title="数据安全与保密规范",
        passages=[
            CorpusPassage(
                "数据 安全 保密 规范 敏感 数据 加密 传输 存储 访问 最小 权限 审计 日志",
                page_no=1,
            ),
            CorpusPassage(
                "密钥 管理 禁止 硬编码 代码 仓库 密钥 轮换 周期 九十 天 泄漏 立即 吊销",
                page_no=2, bbox=[0.05, 0.50, 0.95, 0.65],
            ),
        ],
    ),
    CorpusDoc(
        slug="expense_rates",
        title="各类费用报销标准表",
        passages=[
            CorpusPassage(
                "费用 报销 标准 表 交通 高铁 二等座 飞机 经济舱 住宿 一线 城市 六百 "
                "餐补 每日 一百 五十 元 通讯 补贴 每月 二百",
                page_no=1, bbox=[0.05, 0.20, 0.95, 0.80],
            ),
        ],
    ),
    CorpusDoc(
        slug="release_process",
        title="产品发布流程规范",
        passages=[
            CorpusPassage(
                "产品 发布 流程 规范 需求 评审 开发 联调 测试 验收 灰度 发布 全量",
                page_no=1,
            ),
            CorpusPassage(
                "灰度 策略 百分之五 百分之 二十 百分之 五十 全量 观察 时长 二十四 小时",
                page_no=5, bbox=[0.08, 0.35, 0.92, 0.50],
            ),
        ],
    ),
    CorpusDoc(
        slug="onboarding",
        title="新员工入职指南",
        passages=[
            CorpusPassage(
                "新员工 入职 指南 报到 第一天 领取 设备 开通 账号 配置 权限 导师 分配",
                page_no=1,
            ),
            CorpusPassage(
                "试用期 三个月 转正 考核 导师 评估 培训 课程 完成 证书",
                page_no=6,
            ),
        ],
    ),
    CorpusDoc(
        slug="code_review",
        title="代码评审规范",
        passages=[
            CorpusPassage(
                "代码 评审 规范 合并 请求 必须 至少 一人 审查 单元 测试 覆盖 率 百分之八十",
                page_no=1,
            ),
            CorpusPassage(
                "审查 要点 命名 清晰 边界 条件 异常 处理 安全 漏洞 性能 瓶颈",
                page_no=2, bbox=[0.10, 0.25, 0.90, 0.40],
            ),
        ],
    ),
    CorpusDoc(
        slug="dc_inspection",
        title="机房巡检作业指导书",
        passages=[
            CorpusPassage(
                "机房 巡检 作业 指导书 温度 二十二 度 湿度 百分之四十五 每日 巡检 两次",
                page_no=1, bbox=[0.07, 0.18, 0.93, 0.30],
            ),
            CorpusPassage(
                "巡检 项目 供电 ups 空调 消防 线缆 标签 异常 上报 工单",
                page_no=3,
            ),
        ],
    ),
    CorpusDoc(
        slug="offboarding",
        title="员工离职交接流程",
        passages=[
            CorpusPassage(
                "员工 离职 交接 流程 提前 三十 天 申请 交接 清单 设备 归还 账号 回收",
                page_no=1,
            ),
            CorpusPassage(
                "知识 交接 文档 沉淀 项目 手册 继任者 确认 离职 证明 社保 转移",
                page_no=2,
            ),
        ],
    ),
]


# ===== 评估用例（~20；slug 在 seed 时解析为 expected_doc_ids） =====
EVAL_CASES: List[CorpusCase] = [
    # --- 普通文本召回（单关键词） ---
    CorpusCase("c_travel_apply", "出差 申请 审批 流程", ["travel_policy"], tags=["text", "travel"]),
    CorpusCase("c_leave_days", "年假 多少 天", ["leave_policy"], gold_answer="工龄 满一年 五天 满五年 十天", tags=["text", "leave"]),
    CorpusCase("c_release_window", "发布 窗口 什么时候", ["ops_runbook"], tags=["text", "ops"]),
    CorpusCase("c_review_coverage", "单元 测试 覆盖率 要求", ["code_review"], tags=["text", "quality"]),
    CorpusCase("c_onboard_day1", "入职 第一天 做 什么", ["onboarding"], tags=["text", "hr"]),

    # --- 多关键词 / 跨文档 ---
    CorpusCase("c_expense_two", "出差 住宿 报销 标准", ["travel_policy", "expense_rates"], tags=["text", "multi"]),
    CorpusCase("c_security_key", "密钥 管理 轮换", ["security_policy"], gold_answer="禁止 硬编码 轮换 九十 天", tags=["text", "security"]),

    # --- 表格内容召回 ---
    CorpusCase("c_rates_table", "费用 报销 标准 表 餐补", ["expense_rates"], expected_page=1, tags=["table"]),

    # --- bbox 溯源（期望定位到具体区域） ---
    CorpusCase(
        "c_travel_lodging_bbox", "住宿 标准 一线 城市 每晚",
        ["travel_policy"], expected_page=3, expected_bbox=[0.08, 0.40, 0.92, 0.55], tags=["bbox"],
    ),
    CorpusCase(
        "c_dc_temp_bbox", "机房 温度 湿度 巡检",
        ["dc_inspection"], expected_page=1, expected_bbox=[0.07, 0.18, 0.93, 0.30], tags=["bbox"],
    ),
    CorpusCase(
        "c_gray_bbox", "灰度 策略 百分比",
        ["release_process"], expected_page=5, expected_bbox=[0.08, 0.35, 0.92, 0.50], tags=["bbox"],
    ),

    # --- 多轮/指代消解式（query 自带足够上下文） ---
    CorpusCase("c_handover", "离职 交接 设备 归还 账号", ["offboarding"], tags=["text", "multi"]),
    CorpusCase("c_fire_window", "禁止 周五 发布 回滚 预案", ["ops_runbook"], tags=["text", "ops"]),

    # --- 无答案（语料中不存在的话题；期望低召回/空） ---
    CorpusCase("c_noanswer_tax", "薪资 个税 计算 公式 速算 扣除", [], tags=["no_answer"]),
    CorpusCase("c_noanswer_market", "市场 预算 投放 渠道 ROI 转化", [], tags=["no_answer"]),
]

# 便于 seed / 文档化
SCENE_ID_DEFAULT = "eval"
KB_NAME_DEFAULT = "Eval Corpus"
