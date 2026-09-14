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


# ===== 语料文档（空格分词；22 篇） =====
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
    # ---- 扩充批次（plan_four §2 补齐：10 → 22 篇，主题与既有词面保持区分度） ----
    CorpusDoc(
        slug="meeting_rooms",
        title="会议室预订管理规范",
        passages=[
            CorpusPassage(
                "会议室 预订 管理 规范 提前 三 天 预约 单次 时长 不超过 两 小时",
                page_no=1,
            ),
            CorpusPassage(
                "超时 未 使用 系统 自动 释放 会议室 违约 三次 冻结 预订 权限 一 月",
                page_no=2, bbox=[0.08, 0.28, 0.90, 0.42],
            ),
        ],
    ),
    CorpusDoc(
        slug="vpn_access",
        title="远程办公 VPN 接入指引",
        passages=[
            CorpusPassage(
                "远程 办公 vpn 接入 指南 双因素 认证 动态 口令 客户端 下载 安装",
                page_no=1,
            ),
            CorpusPassage(
                "vpn 会话 超时 三十 分钟 自动 断开 重连 需要 重新 认证 境外 访问 需 报备",
                page_no=3, bbox=[0.05, 0.45, 0.95, 0.60],
            ),
        ],
    ),
    CorpusDoc(
        slug="asset_mgmt",
        title="固定资产管理规定",
        passages=[
            CorpusPassage(
                "固定 资产 管理 规定 价值 超过 两千 元 入账 资产 编码 贴标 归属 部门",
                page_no=1,
            ),
            CorpusPassage(
                "资产 盘点 每年 一次 十二 月 执行 盘盈 盘亏 说明 报 财务 备案",
                page_no=4,
            ),
        ],
    ),
    CorpusDoc(
        slug="procurement",
        title="采购与供应商管理办法",
        passages=[
            CorpusPassage(
                "采购 供应商 管理 办法 单笔 超过 五万 元 需要 三家 比价 合同 会签",
                page_no=1,
            ),
            CorpusPassage(
                "供应商 准入 资质 审查 年度 评级 不合格 淘汰 紧急 采购 事后 补办",
                page_no=2, bbox=[0.10, 0.32, 0.88, 0.46],
            ),
        ],
    ),
    CorpusDoc(
        slug="training_platform",
        title="在线培训平台使用说明",
        passages=[
            CorpusPassage(
                "培训 平台 使用 说明 账号 工号 登录 选修 必修 学分 每年 不少于 二十",
                page_no=1,
            ),
            CorpusPassage(
                "学习 记录 自动 计入 档案 学分 不 足 影响 晋升 评优 补修 通道 年底 关闭",
                page_no=2,
            ),
        ],
    ),
    CorpusDoc(
        slug="incident_sev",
        title="故障分级与上报标准",
        passages=[
            CorpusPassage(
                "故障 分级 上报 标准 p1 核心 业务 不可用 影响 面 超过 百分之 五十",
                page_no=1, bbox=[0.06, 0.20, 0.92, 0.36],
            ),
            CorpusPassage(
                "p1 五 分钟 内 上报 值班 经理 p2 三十 分钟 内 上报 组长 每级 复盘 报告",
                page_no=2,
            ),
        ],
    ),
    CorpusDoc(
        slug="api_style",
        title="内部 API 设计规范",
        passages=[
            CorpusPassage(
                "内部 api 设计 规范 路径 小写 复数 名词 版本 号 前缀 v1 向后 兼容",
                page_no=1,
            ),
            CorpusPassage(
                "错误 返回 结构 code message detail 分页 cursor 避免 offset 深翻页",
                page_no=5, bbox=[0.08, 0.40, 0.92, 0.55],
            ),
        ],
    ),
    CorpusDoc(
        slug="db_backup",
        title="数据库备份与恢复策略",
        passages=[
            CorpusPassage(
                "数据库 备份 恢复 策略 全量 每日 一次 增量 每小时 保留 三十 天",
                page_no=1, bbox=[0.07, 0.22, 0.93, 0.38],
            ),
            CorpusPassage(
                "恢复 演练 每季度 一次 演练 记录 归档 rpo 十五 分钟 rto 四 小时",
                page_no=3,
            ),
        ],
    ),
    CorpusDoc(
        slug="customer_sla",
        title="客服服务承诺与响应标准",
        passages=[
            CorpusPassage(
                "客服 服务 承诺 响应 标准 首次 响应 十五 分钟 内 解决 时效 四 小时",
                page_no=1,
            ),
            CorpusPassage(
                "客户 满意度 回访 每月 抽查 投诉 升级 通道 重大 投诉 二十四 小时 内 答复",
                page_no=2,
            ),
        ],
    ),
    CorpusDoc(
        slug="archive_mgmt",
        title="档案管理制度",
        passages=[
            CorpusPassage(
                "档案 管理 制度 合同 财务 人事 档案 分类 保管 期限 十年 三十年 永久",
                page_no=1,
            ),
            CorpusPassage(
                "档案 借阅 审批 登记 复印 盖章 原件 不 外 带 电子 档案 双 备份",
                page_no=6,
            ),
        ],
    ),
    CorpusDoc(
        slug="meeting_minutes",
        title="例会与会议纪要规范",
        passages=[
            CorpusPassage(
                "例会 纪要 规范 周一 主管 例会 周三 全员 例会 纪要 二十四 小时 内 发出",
                page_no=1,
            ),
            CorpusPassage(
                "纪要 格式 决议 事项 负责 人 截止 时间 跟进 项 下次 例会 回顾",
                page_no=2, bbox=[0.10, 0.30, 0.90, 0.44],
            ),
        ],
    ),
    CorpusDoc(
        slug="badge_visitor",
        title="访客门禁与工牌管理规定",
        passages=[
            CorpusPassage(
                "访客 门禁 工牌 管理 规定 访客 预约 登记 陪同 人 负责 制 工牌 随身 佩戴",
                page_no=1,
            ),
            CorpusPassage(
                "工牌 遗失 挂失 补办 费用 五十 元 离职 交回 门禁 权限 即时 回收",
                page_no=3, bbox=[0.06, 0.35, 0.94, 0.50],
            ),
        ],
    ),
]


# ===== 评估用例（22；slug 在 seed 时解析为 expected_doc_ids） =====
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

    # --- 扩充批次（+5；锚定新文档，词面与既有文档保持区分度） ---
    CorpusCase("c_meeting_book", "会议室 预订 提前 多久", ["meeting_rooms"], gold_answer="提前 三 天 预约", tags=["text", "meeting"]),
    CorpusCase("c_vpn_session", "vpn 会话 超时 断开", ["vpn_access"], tags=["text", "vpn"]),
    CorpusCase("c_incident_p1", "p1 故障 上报 时限", ["incident_sev"], gold_answer="五 分钟 上报 值班 经理", tags=["text", "ops"]),
    CorpusCase("c_api_version", "api 路径 版本 规范", ["api_style"], tags=["text", "dev"]),
    CorpusCase(
        "c_backup_freq_bbox", "数据库 全量 备份 频率 保留",
        ["db_backup"], expected_page=1, expected_bbox=[0.07, 0.22, 0.93, 0.38], tags=["bbox", "ops"],
    ),
    CorpusCase("c_asset_check", "资产 盘点 每年 月份", ["asset_mgmt"], tags=["text", "finance"]),
    CorpusCase("c_archive_loan", "档案 借阅 复印 规定", ["archive_mgmt"], tags=["text", "admin"]),

    # --- 无答案（语料中不存在的话题；期望低召回/空） ---
    CorpusCase("c_noanswer_tax", "薪资 个税 计算 公式 速算 扣除", [], tags=["no_answer"]),
    CorpusCase("c_noanswer_market", "市场 预算 投放 渠道 ROI 转化", [], tags=["no_answer"]),
]

# 便于 seed / 文档化
SCENE_ID_DEFAULT = "eval"
KB_NAME_DEFAULT = "Eval Corpus"
