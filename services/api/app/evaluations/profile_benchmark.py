"""按调研档位生成确定性分析包，并执行离线 benchmark 校验。"""

from __future__ import annotations

from typing import Any

from app.reports.renderer import render_report_markdown
from app.research.profiles import get_research_profile
from app.verifiers.package import as_list, value_of, verify_analysis_package
from app.verifiers.quality import score_analysis_package


PROFILE_FINDING_CATEGORIES = {
    # 每个调研档位至少要能生成与其目标对应的 finding 分类。
    "quick_onboarding": ["reading_path"],
    "architecture_understanding": ["architecture_module_boundary"],
    "extension_evaluation": ["extension"],
    "teaching_breakdown": ["teaching_learning_path", "practice_exercise"],
    "delivery_acceptance": ["delivery_readiness"],
}

PROFILE_RISK_KEYS = {
    # 只有这些档位强制要求风险登记；快速接手和架构理解不强制造风险。
    "extension_evaluation",
    "teaching_breakdown",
    "delivery_acceptance",
}


def evaluate_profile_benchmark(case: Any, scan_result: dict[str, Any]) -> dict[str, Any]:
    """执行调研档位 benchmark 的确定性垂直切片。

    处理链路模拟正式 Analysis Package 的核心消费顺序：

    1. 从只读扫描结果构造 inventory 和 package；
    2. 按 profile 权重计算质量分；
    3. 运行确定性 verifier；
    4. 渲染 Markdown 并提取实际章节；
    5. 校验 profile 检查、报告章节、bundle 状态和证据引用。

    该函数不触发 LLM、网络或数据库，因此适合作为稳定的 CI 回归检查。
    """

    profile = resolve_benchmark_profile(case)
    # inventory/package 都是内存结构，字段命名刻意贴近正式 ORM 的序列化形状。
    inventory = build_profile_inventory(case, scan_result)
    package = build_profile_package(case, scan_result)

    # 质量评分必须先写入 package，后续 verifier 才能检查 quality_scores 是否齐全。
    quality = score_analysis_package(
        snapshots=inventory["snapshots"],
        codebase_maps=normalize_codebase_for_quality(inventory["codebase_maps"]),
        evidence=package["evidence_items"],
        findings=package["findings"],
        risks=package["risks"],
        questions=package["questions"],
        recommendations=package["recommendations"],
        previous_overall=None,
        research_profile=profile.key,
    )
    package["quality_scores"].append(quality_score_item(quality))

    # verifier 是最终 passed 的必要条件；benchmark checks 只验证 profile 专属契约。
    verifier_result = verify_analysis_package(package, inventory)
    # 报告实际渲染后再提取二级标题，避免只检查配置常量却漏掉渲染器回归。
    markdown = render_report_markdown(package["project"], package, inventory, verifier_result)
    report_sections = extract_markdown_sections(markdown)
    profile_checks = extract_profile_checks(verifier_result)
    checks = build_benchmark_checks(
        case=case,
        profile=profile,
        package=package,
        inventory=inventory,
        quality=quality,
        verifier_result=verifier_result,
        report_sections=report_sections,
        profile_checks=profile_checks,
    )

    expected_checks = list(case.expected_checks)
    check_names = [check["name"] for check in checks]
    missing_checks = [name for name in expected_checks if name not in check_names]
    unexpected_checks = [name for name in check_names if name not in expected_checks]
    # benchmark 通过必须同时满足：verifier 通过、check 集合完全匹配、每项 check 通过。
    passed = (
        bool(verifier_result.get("passed"))
        and not missing_checks
        and not unexpected_checks
        and all(check["passed"] for check in checks)
    )

    return {
        "case_id": case.case_id,
        "description": case.description,
        "case_type": "profile_benchmark",
        "passed": passed,
        "expected_checks": expected_checks,
        "missing_checks": missing_checks,
        "unexpected_checks": unexpected_checks,
        "checks": checks,
        "research_profile": {"key": profile.key, "label": profile.label},
        "profile_checks": profile_checks,
        "quality_summary": {
            "overall_score": quality["overall_score"],
            "metadata_profile": value_of(quality.get("metadata", {}), "research_profile"),
        },
        "report_sections": report_sections,
        "bundle_summary": first_bundle_summary(inventory),
    }


def build_profile_inventory(case: Any, scan_result: dict[str, Any]) -> dict[str, Any]:
    """把扫描结果包装成 verifier 和质量评分需要的 inventory 形状。

    这里不创建数据库记录，只生成一份确定性的内存清单。字段使用 ``*_json``
    后缀，是为了模拟正式 API 从 ORM 序列化后的键名。
    """

    bundle_status = resolve_bundle_status(scan_result)
    return {
        # 每个 benchmark case 固定视为一个已采集的本地目录快照。
        "snapshots": [
            {
                "id": f"{case.case_id}-snapshot",
                "source_type": "local_directory",
                "status": "collected",
                "title": case.description,
            }
        ],
        # 单次 benchmark 只对应一个 fixture 根目录，因此固定生成一张 codebase map。
        "codebase_maps": [
            {
                "id": f"{case.case_id}-codebase",
                "root_label": case.case_id,
                "tech_stack_json": scan_result["tech_stack"],
                "dependency_files_json": scan_result["dependency_files"],
                "config_files_json": scan_result["config_files"],
                "test_files_json": scan_result["test_files"],
                "entrypoint_files_json": scan_result["entrypoint_files"],
                "readme_excerpt": scan_result["readme_excerpt"],
                "file_tree_json": scan_result["file_tree"],
                "skipped_items_json": scan_result["skipped_items"],
            }
        ],
        # bundle 计数由状态推导，确保 collected/failed/pending 三者的计数不会互相矛盾。
        "source_bundles": [
            {
                "name": f"{case.case_id} benchmark bundle",
                "status": bundle_status,
                "item_count": 1 if bundle_status in {"collected", "failed"} else 0,
                "collected_count": 1 if bundle_status == "collected" else 0,
                "failed_count": 1 if bundle_status == "failed" else 0,
                "pending_count": 1 if bundle_status == "pending" else 0,
            }
        ],
    }


def build_profile_package(case: Any, scan_result: dict[str, Any]) -> dict[str, Any]:
    """构造接近正式 Analysis Package 的最小确定性分析包。

    findings、risks 和 questions 会根据 profile 与扫描线索条件生成；evidence id
    统一由 case_id 派生，便于后续验证所有引用都能解析到同一个证据对象。
    """

    profile = resolve_benchmark_profile(case)
    evidence_id = f"{case.case_id}-evidence"
    evidence_items = [
        {
            "id": evidence_id,
            "title": f"{case.case_id} codebase evidence",
            "summary": evidence_summary(scan_result),
            "evidence_type": "codebase",
            "reference": case.case_id,
            "confidence": 90,
        }
    ]
    findings = profile_findings(profile.key, evidence_id, scan_result)
    risks = profile_risks(profile.key, evidence_id, scan_result)
    questions = profile_questions(profile.key, scan_result)
    recommendations = [
        {
            "id": f"{case.case_id}-recommendation",
            "summary": "Use the benchmark package as the profile acceptance snapshot.",
            "rationale": "The package records inventory, profile findings, risks, and evidence links.",
            "confidence": 90,
            "next_steps_json": ["Review profile checks", "Render benchmark report"],
        }
    ]

    return {
        # profile summary 使用新列表复制 profile 配置，防止调用方修改内存中的注册表对象。
        "research_profile": profile.key,
        "profile_summary": {
            "key": profile.key,
            "label": profile.label,
            "description": profile.description,
            "checklist": list(profile.checklist),
            "verifier_checks": list(profile.verifier_checks),
            "report_sections": list(profile.report_sections),
            "required_evidence_types": list(profile.required_evidence_types),
        },
        "project": {
            "id": f"{case.case_id}-project",
            "name": case.description,
            "topic": case.description,
            "analysis_goal": f"Evaluate the {profile.key} research profile benchmark.",
            "status": "ready_for_review",
            "research_profile": profile.key,
        },
        "run": {
            "id": f"{case.case_id}-run",
            "status": "ready_for_review",
            "research_profile": profile.key,
        },
        "turns": [
            {
                "id": f"{case.case_id}-turn",
                "turn_index": 1,
                "node_name": "profile_benchmark",
                "action": "Build deterministic benchmark package.",
                "observation": "Synthetic profile package created from readonly code scan output.",
                "metadata_json": {"case_id": case.case_id, "research_profile": profile.key},
            }
        ],
        # 评测包同时保留通用 evidence 和现有 verifier 使用的 evidence_items 命名。
        "evidence": evidence_items,
        "evidence_items": evidence_items,
        "findings": findings,
        "risks": risks,
        "questions": questions,
        "recommendations": recommendations,
        "quality_scores": [],
    }


def evidence_summary(scan_result: dict[str, Any]) -> str:
    """生成可读的扫描证据摘要，只统计确定性文件线索。"""

    return (
        "Readonly scan found "
        f"{len(scan_result.get('entrypoint_files', []))} entrypoints, "
        f"{len(scan_result.get('dependency_files', []))} dependency files, "
        f"and {len(scan_result.get('test_files', []))} test files."
    )


def resolve_benchmark_profile(case: Any) -> Any:
    """解析并校验 case 声明的调研档位。

    不能直接信任任意 profile key：benchmark 只覆盖本模块显式支持的五种档位，
    未支持的值应在构造分析包之前失败。
    """

    profile_key = value_of(case, "research_profile")
    if profile_key not in PROFILE_FINDING_CATEGORIES:
        raise ValueError(f"Unsupported profile benchmark research profile `{profile_key}`.")
    return get_research_profile(profile_key)


def resolve_bundle_status(scan_result: dict[str, Any]) -> str:
    """根据扫描结果推导资料包状态。

    有错误时为 failed；有任何可消费代码/README 线索时为 collected；完全没有
    可用内容时保持 pending。该状态会进入 bundle 摘要并被 benchmark check 校验。
    """

    if scan_result.get("collection_error") or scan_result.get("error"):
        return "failed"
    if scan_has_any(scan_result, "file_tree", "entrypoint_files", "dependency_files", "test_files") or scan_result.get(
        "readme_excerpt"
    ):
        return "collected"
    return "pending"


def profile_findings(profile_key: str, evidence_id: str, scan_result: dict[str, Any]) -> list[dict[str, Any]]:
    """按 profile 可识别的扫描线索生成带证据引用的 findings。"""

    categories = profile_finding_categories(profile_key, scan_result)
    return [
        finding(
            title=f"{profile_key} benchmark finding: {category}",
            category=category,
            evidence_id=evidence_id,
        )
        for category in categories
    ]


def profile_finding_categories(profile_key: str, scan_result: dict[str, Any]) -> list[str]:
    """根据调研档位解释扫描结果，返回该档位应生成的 finding 分类。

    分类不是固定为每个档位硬造一条：只有 fixture 具备相应线索时才生成，
    这样 verifier 才能发现“输入不足却仍宣称分析完成”的伪造产物。
    """

    if profile_key == "quick_onboarding":
        return ["reading_path"] if scan_has_any(scan_result, "entrypoint_files", "config_files", "test_files") else []
    if profile_key == "architecture_understanding":
        return ["architecture_module_boundary"] if scan_has_any(scan_result, "file_tree", "entrypoint_files") else []
    if profile_key == "extension_evaluation":
        return ["extension"] if scan_has_any(scan_result, "test_files", "config_files", "dependency_files") else []
    if profile_key == "teaching_breakdown":
        # 教学路径依赖入口/目录线索，练习任务依赖测试文件，两者可以独立出现。
        categories = []
        if scan_has_any(scan_result, "entrypoint_files", "file_tree"):
            categories.append("teaching_learning_path")
        if scan_has_any(scan_result, "test_files"):
            categories.append("practice_exercise")
        return categories
    if profile_key == "delivery_acceptance":
        return ["delivery_readiness"] if scan_has_delivery_clues(scan_result) else []
    raise ValueError(f"Unsupported profile benchmark research profile `{profile_key}`.")


def profile_risks(profile_key: str, evidence_id: str, scan_result: dict[str, Any]) -> list[dict[str, Any]]:
    """为需要风险可见性的 profile 生成带缓解建议的风险项。

    扩展评估、教学拆解和交付验收要求风险台账；如果输入线索不足，则返回空列表，
    让 verifier 明确报错，而不是生成一条无法解释的通用风险。
    """

    if profile_key not in PROFILE_FINDING_CATEGORIES:
        raise ValueError(f"Unsupported profile benchmark research profile `{profile_key}`.")
    if profile_key not in PROFILE_RISK_KEYS:
        return []
    if profile_key == "extension_evaluation" and not scan_has_any(
        scan_result,
        "test_files",
        "config_files",
        "dependency_files",
    ):
        return []
    if profile_key == "teaching_breakdown" and not scan_has_any(scan_result, "file_tree", "test_files"):
        return []
    if profile_key == "delivery_acceptance" and not scan_has_delivery_clues(scan_result):
        return []
    return [
        {
            "id": f"{profile_key}-risk",
            "title": f"{profile_key} profile risk",
            "summary": "Profile-specific acceptance depends on keeping evidence and mitigation explicit.",
            "severity": "medium",
            "mitigation": "Review the generated profile checks and update the benchmark fixture before extending scope.",
            "evidence_refs_json": [evidence_id],
            "evidence_refs": [evidence_id],
        }
    ]


def profile_questions(profile_key: str, scan_result: dict[str, Any]) -> list[dict[str, Any]]:
    """生成 profile 专属问题。

    当前只有交付验收需要一条已回答的 handoff 问题，用于验证 verifier 能区分
    open 与 answered 状态，并确认交付总结有明确的人工确认。
    """

    if profile_key not in PROFILE_FINDING_CATEGORIES:
        raise ValueError(f"Unsupported profile benchmark research profile `{profile_key}`.")
    if profile_key != "delivery_acceptance":
        return []
    if not scan_result.get("readme_excerpt"):
        return []
    return [
        {
            "id": f"{profile_key}-question",
            "prompt": "Is the handoff package acceptable for benchmark delivery?",
            "reason": "Delivery acceptance requires an explicit answered handoff question.",
            "impact": "medium",
            "status": "answered",
            "answer_text": "Yes; the benchmark package includes runbook clues and evidence references.",
        }
    ]


def scan_has_any(scan_result: dict[str, Any], *keys: str) -> bool:
    """判断一组扫描字段中是否至少有一个非空值。"""

    return any(bool(scan_result.get(key)) for key in keys)


def scan_has_delivery_clues(scan_result: dict[str, Any]) -> bool:
    """判断是否具备交付验收所需的最低线索：README 加至少一种工程文件。"""

    return bool(scan_result.get("readme_excerpt")) and scan_has_any(
        scan_result,
        "entrypoint_files",
        "dependency_files",
        "config_files",
    )


def finding(title: str, category: str, evidence_id: str) -> dict[str, Any]:
    """构造一条确定性的 benchmark finding，并绑定唯一证据引用。"""

    return {
        "id": f"{category}-finding",
        "title": title,
        "summary": "Synthetic benchmark finding anchored to the readonly codebase evidence.",
        "category": category,
        "impact_level": "medium",
        "confidence": 90,
        "evidence_refs_json": [evidence_id],
        "evidence_refs": [evidence_id],
    }


def benchmark_check(name: str, passed: bool, message: str) -> dict[str, Any]:
    """构造 profile benchmark 的统一检查结果。"""

    return {"name": name, "passed": passed, "message": message}


def build_benchmark_checks(
    *,
    case: Any,
    profile: Any,
    package: dict[str, Any],
    inventory: dict[str, Any],
    quality: dict[str, Any],
    verifier_result: dict[str, Any],
    report_sections: list[str],
    profile_checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """生成调研档位 benchmark 的七项固定检查。

    检查覆盖 profile 一致性、profile verifier、质量权重、报告章节、bundle 摘要
    和证据引用完整性。调用方还会额外比较检查名称集合，防止检查被静默删除。
    """

    quality_metadata = quality.get("metadata", {})
    passed_profile_checks = {check["name"] for check in profile_checks if check["passed"]}
    missing_profile_checks = [
        check_name for check_name in case.expected_profile_checks if check_name not in passed_profile_checks
    ]
    missing_report_sections = [
        section for section in case.expected_report_sections if section not in report_sections
    ]
    bundle_summary = first_bundle_summary(inventory)
    expected_bundle_status = case.expected_bundle_status or "collected"

    # 前四项确认 profile 被一路传递且质量评分使用了对应权重。
    return [
        benchmark_check(
            "profile_key_matches",
            value_of(verifier_result.get("research_profile", {}), "key") == profile.key
            and value_of(package.get("project", {}), "research_profile") == profile.key
            and value_of(package.get("run", {}), "research_profile") == profile.key,
            f"Expected profile `{profile.key}`.",
        ),
        benchmark_check(
            "profile_checks_passed",
            not missing_profile_checks,
            (
                "All expected profile checks passed."
                if not missing_profile_checks
                else f"Missing expected profile checks: {', '.join(missing_profile_checks)}"
            ),
        ),
        benchmark_check(
            "quality_metadata_profile",
            value_of(quality_metadata, "research_profile") == profile.key,
            f"Quality metadata profile is `{value_of(quality_metadata, 'research_profile')}`.",
        ),
        benchmark_check(
            "quality_metadata_weights",
            value_of(quality_metadata, "quality_weights") == profile.quality_weights,
            "Quality metadata includes the active profile weights.",
        ),
        benchmark_check(
            "report_sections_present",
            not missing_report_sections,
            (
                "All expected report sections are present."
                if not missing_report_sections
                else f"Missing report sections: {', '.join(missing_report_sections)}"
            ),
        ),
        # bundle 摘要必须存在且包含至少一个 item，避免报告展示空资料包。
        benchmark_check(
            "bundle_summary_present",
            value_of(bundle_summary, "status") == expected_bundle_status
            and int(value_of(bundle_summary, "item_count", 0) or 0) >= 1,
            (
                f"Expected bundle status `{expected_bundle_status}`, "
                f"actual `{value_of(bundle_summary, 'status', 'missing')}`, "
                f"item_count `{value_of(bundle_summary, 'item_count', 0)}`."
            ),
        ),
        # 所有 finding/risk 的引用都必须能解析到 package 中已有的 evidence id。
        benchmark_check(
            "evidence_refs_valid",
            evidence_refs_valid(package),
            "Finding and risk evidence references resolve to package evidence ids.",
        ),
    ]


def normalize_codebase_for_quality(codebase_maps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 ORM 风格的 ``*_json`` 字段转换为质量评分器读取的普通字段。

    转换只增加目标键，不删除原始键，避免调用方依赖的序列化字段丢失。
    """

    normalized: list[dict[str, Any]] = []
    key_map = {
        "tech_stack_json": "tech_stack",
        "dependency_files_json": "dependency_files",
        "config_files_json": "config_files",
        "test_files_json": "test_files",
        "entrypoint_files_json": "entrypoint_files",
        "file_tree_json": "file_tree",
        "skipped_items_json": "skipped_items",
    }
    for codebase_map in codebase_maps:
        item = dict(codebase_map)
        for source_key, target_key in key_map.items():
            if source_key in item:
                item[target_key] = item[source_key]
        normalized.append(item)
    return normalized


def quality_score_item(quality: dict[str, Any]) -> dict[str, Any]:
    """把评分器输出包装成与 ORM 序列化一致的 quality score 条目。"""

    return {
        **quality,
        "reasons_json": quality.get("reasons", []),
        "next_actions_json": quality.get("next_actions", []),
        "metadata_json": quality["metadata"],
    }


def extract_markdown_sections(markdown: str) -> list[str]:
    """提取 Markdown 中所有二级标题，用于验证报告章节契约。"""

    return [line[3:].strip() for line in markdown.splitlines() if line.startswith("## ")]


def evidence_refs_valid(package: dict[str, Any]) -> bool:
    """验证 findings 和 risks 的每个证据引用都能解析到已有 evidence。

    任一条 finding/risk 没有引用，或引用了 package 中不存在的 evidence id，
    都返回 False。package 没有任何 evidence 时同样失败。
    """

    evidence_ids = {
        str(value_of(evidence, "id"))
        for evidence in as_list(package.get("evidence_items"))
        if value_of(evidence, "id")
    }
    for item in [*as_list(package.get("findings")), *as_list(package.get("risks"))]:
        refs = [
            str(ref)
            for key in ("evidence_refs_json", "evidence_refs")
            for ref in as_list(value_of(item, key, []))
        ]
        if not refs or any(str(ref) not in evidence_ids for ref in refs):
            return False
    return bool(evidence_ids)


def extract_profile_checks(verifier_result: dict[str, Any]) -> list[dict[str, Any]]:
    """从完整 verifier 结果中提取 ``profile:*`` 检查并扁平化消息。"""

    checks = []
    for check in as_list(verifier_result.get("checks")):
        name = str(value_of(check, "name", ""))
        if not name.startswith("profile:"):
            continue
        messages = [str(message) for message in as_list(value_of(check, "messages", []))]
        checks.append(
            {
                "name": name,
                "passed": bool(value_of(check, "passed", False)),
                "message": " ".join(messages),
            }
        )
    return checks


def first_bundle_summary(inventory: dict[str, Any]) -> dict[str, Any]:
    """返回资料包摘要；benchmark 固定只生成一个 bundle，缺失时返回空对象。"""

    bundles = as_list(inventory.get("source_bundles"))
    return bundles[0] if bundles else {}
