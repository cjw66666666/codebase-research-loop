"""Analysis Package 的确定性质量评分规则。

这里不评价文字是否“写得漂亮”，而是根据结构化产物是否齐全、是否带证据、
风险是否可执行以及开放问题是否解决等可复现信号计算分数。六个维度统一落到
0-100 分，再按调研档位对应的权重汇总为 overall_score。
"""

from app.research.profiles import get_research_profile


def clamp(value: int) -> int:
    """把单项评分限制在 0-100 之间。"""

    return max(0, min(100, value))


def score_structure(snapshots: list[dict], findings: list[dict], recommendations: list[dict]) -> int:
    """按输入快照、分析发现和建议三个核心部分是否齐全计算结构分。"""

    score = 0
    if snapshots:
        score += 35
    if findings:
        score += 35
    if recommendations:
        score += 30
    return score


def score_evidence(evidence: list[dict], findings: list[dict]) -> int:
    """计算带有证据引用的 findings 占比。

    只要有证据和 findings 就进入比例计算；某条 finding 没有 evidence_refs
    时，该条视为未覆盖。返回 0 表示证据链尚未建立。
    """

    if not evidence or not findings:
        return 0
    supported = sum(1 for finding in findings if finding.get("evidence_refs"))
    return clamp(int((supported / len(findings)) * 100))


def score_codebase(codebase_maps: list[dict]) -> tuple[int, list[str]]:
    """计算代码库覆盖度，并返回缺失测试时建议采取的下一步动作。

    每个代码库地图独立按五项线索计分，再对所有地图取平均：
    技术栈 25、依赖文件 20、入口文件 20、README 20、测试文件 15。
    当前规则只判断线索是否存在，不判断文件数量、内容质量或测试是否可运行。
    """

    if not codebase_maps:
        # 纯文档或其他非代码输入没有代码库可评，当前设计不因此扣分。
        return 100, []

    next_actions: list[str] = []
    per_map_scores: list[int] = []
    for codebase_map in codebase_maps:
        # 每项只要至少存在一个有效线索即可获得该项满分。
        score = 0
        if codebase_map.get("tech_stack"):
            score += 25
        if codebase_map.get("dependency_files"):
            score += 20
        if codebase_map.get("entrypoint_files"):
            score += 20
        if codebase_map.get("readme_excerpt"):
            score += 20
        if codebase_map.get("test_files"):
            score += 15
        else:
            # 测试缺失不仅少 15 分，还要求后续补充可验证的行为证据。
            next_actions.append("为扫描到的代码库补充测试，或提供测试证据。")
        per_map_scores.append(score)
    # 多个代码库地图等权平均，避免代码库数量更多的一方支配最终分数。
    return int(sum(per_map_scores) / len(per_map_scores)), next_actions


def score_risks(risks: list[dict]) -> int:
    """计算风险记录的可执行程度，而不是风险数量。

    没有风险时视为风险透明度满分；存在风险时，只有同时给出 severity 和
    mitigation 的记录才算完整。广泛列出风险但缺少缓解方案不会得到高分。
    """

    if not risks:
        return 100
    complete = sum(1 for risk in risks if risk.get("severity") and risk.get("mitigation"))
    return clamp(int((complete / len(risks)) * 100))


def score_questions(questions: list[dict]) -> tuple[int, list[str]]:
    """按开放问题的影响级别计算问题关闭率，并返回处理建议。

    高影响问题未解决会阻断评审，因此直接压到 40 分；仍有普通开放问题时
    给 70 分；全部问题已回答时才是 100 分。
    """

    open_high = [
        question
        for question in questions
        if question.get("status") == "open" and question.get("impact") == "high"
    ]
    if open_high:
        return 40, ["评审前先回答高影响开放问题。"]
    open_any = [question for question in questions if question.get("status") == "open"]
    if open_any:
        return 70, ["处理剩余开放问题。"]
    return 100, []


def score_recommendations(recommendations: list[dict]) -> int:
    """取建议中最高的人工或模型置信度，作为建议可信度。

    这是对建议“自报置信度”的汇总，不是对建议正确性的独立验证；没有建议
    时该维度为 0 分。
    """

    if not recommendations:
        return 0
    return clamp(max(int(recommendation.get("confidence", 0)) for recommendation in recommendations))


def score_analysis_package(
    snapshots: list[dict],
    codebase_maps: list[dict],
    evidence: list[dict],
    findings: list[dict],
    risks: list[dict],
    questions: list[dict],
    recommendations: list[dict],
    previous_overall: int | None,
    research_profile: str | None = None,
) -> dict:
    """计算一份 Analysis Package 的六维质量分和总分。

    评分步骤：
    1. 分别计算六个 0-100 的维度分；
    2. 低于 80 分的维度写入 reasons，并生成对应的改进动作；
    3. 按 research profile 的 quality_weights 加权得到 overall_score；
    4. 与同项目上一次评分比较，得到 score_delta。

    返回值可直接由 QualityScore 模型持久化，也可用于报告和前端展示。
    """

    profile = get_research_profile(research_profile)
    next_actions: list[str] = []
    reasons: list[str] = []
    codebase_coverage, codebase_actions = score_codebase(codebase_maps)
    question_resolution, question_actions = score_questions(questions)
    dimensions = {
        "structure_completeness": score_structure(snapshots, findings, recommendations),
        "evidence_coverage": score_evidence(evidence, findings),
        "codebase_coverage": codebase_coverage,
        "risk_transparency": score_risks(risks),
        "question_resolution": question_resolution,
        "recommendation_confidence": score_recommendations(recommendations),
    }
    # 80 分以下视为存在明显质量缺口，需要在 reasons 和 next_actions 中解释。
    for name, value in dimensions.items():
        if value < 80:
            reasons.append(f"{dimension_label(name)} 得分为 {value}。")
    next_actions.extend(codebase_actions)
    next_actions.extend(question_actions)
    if dimensions["evidence_coverage"] < 80:
        next_actions.append("为所有重要发现补充证据引用。")
    if dimensions["recommendation_confidence"] < 80:
        next_actions.append("通过更多证据或更低风险的范围提高建议可信度。")

    # 各档位权重之和为 1，因此加权结果仍是 0-100 分。
    overall = int(sum(dimensions[name] * profile.quality_weights[name] for name in dimensions))
    # 首次运行时没有历史基线，score_delta 直接等于当前总分。
    score_delta = overall if previous_overall is None else overall - previous_overall
    return {
        **dimensions,
        "overall_score": overall,
        "score_delta": score_delta,
        "reasons": reasons,
        "next_actions": next_actions,
        "metadata": {
            "research_profile": profile.key,
            "quality_weights": dict(profile.quality_weights),
            "checklist": list(profile.checklist),
        },
    }


def dimension_label(name: str) -> str:
    """返回质量维度在原因说明和界面中展示的中文名称。"""

    labels = {
        "structure_completeness": "结构完整度",
        "evidence_coverage": "证据覆盖",
        "codebase_coverage": "代码覆盖",
        "risk_transparency": "风险透明度",
        "question_resolution": "问题关闭率",
        "recommendation_confidence": "建议可信度",
    }
    return labels.get(name, name)
