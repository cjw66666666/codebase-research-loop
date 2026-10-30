"""评估用例调度器：隔离运行扫描回归和调研档位 benchmark。"""

from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.orm import Session

from app.db.models import EvaluationRun, utc_now
from app.evaluations.cases import EvaluationCase, evaluation_cases, write_case_repo
from app.evaluations.profile_benchmark import evaluate_profile_benchmark
from app.reports.renderer import (
    PROFILE_AWARE_SECTION_HEADINGS,
    PROJECT_RESEARCH_SECTION_HEADINGS,
)
from app.research.profiles import list_research_profiles
from app.tools.code_scan_tools import scan_codebase

KNOWN_CASE_TYPES = {"scan_regression", "profile_benchmark"}


def _check(name: str, passed: bool, message: str) -> dict:
    """构造所有评估用例共用的检查结果结构。"""

    return {
        "name": name,
        "passed": passed,
        "message": message,
    }


def _unknown_case_type_result(case: EvaluationCase) -> dict:
    """为未知 case_type 生成失败结果，而不是中断整批评估。

    保留与正常结果一致的字段可以保证 API 响应结构稳定，调用方无需为配置错误
    单独写一套解析逻辑；该 case 仍会被计入总失败数。
    """

    checks = [
        _check(
            "known_case_type",
            False,
            f"未知 evaluation case type: {case.case_type}",
        )
    ]
    expected_check_names = set(case.expected_checks)
    actual_check_names = {check["name"] for check in checks}
    return {
        "case_id": case.case_id,
        "description": case.description,
        "case_type": case.case_type,
        "passed": False,
        "expected_checks": case.expected_checks,
        "missing_checks": sorted(expected_check_names - actual_check_names),
        "unexpected_checks": sorted(actual_check_names - expected_check_names),
        "checks": checks,
    }


def _scan_case(case_root: Path) -> dict:
    """使用受控大小限制扫描单个 fixture，避免评估读取过大的测试文件。"""

    # 评估输出只需要证明基础扫描能力，过大的摘录会放大数据库/响应体并降低测试速度。
    return scan_codebase(case_root, max_file_bytes=256 * 1024, excerpt_chars=500)


def _project_research_package_check() -> dict:
    """确认报告渲染器仍包含 Project Research Package 的核心章节。"""

    # 这是渲染器契约检查，不依赖某个 fixture 的具体内容。
    required_sections = {
        "工程接手指南",
        "启动与运行线索",
        "架构地图",
        "证据索引",
        "后续阅读路径",
    }
    configured_sections = set(PROJECT_RESEARCH_SECTION_HEADINGS)
    missing_sections = sorted(required_sections - configured_sections)
    return _check(
        "project_research_package_sections",
        not missing_sections,
        (
            "项目调研包核心章节已纳入确定性报告渲染器。"
            if not missing_sections
            else f"项目调研包核心章节缺失: {', '.join(missing_sections)}"
        ),
    )


def _profile_aware_report_check() -> dict:
    """确认调研档位报告护栏和教学拆解专用章节仍然存在。"""

    # 固定章节由所有 profile 共享；动态章节则随 profile 配置变化。
    required_static_sections = {"调研 Profile", "资料包摘要"}
    configured_static_sections = set(PROFILE_AWARE_SECTION_HEADINGS)
    missing_static_sections = sorted(
        required_static_sections - configured_static_sections
    )
    profiles_without_sections = [
        profile.key
        for profile in list_research_profiles()
        if not profile.report_sections
    ]
    # 教学拆解最容易在重构报告渲染时丢失专属章节，因此额外做精确检查。
    teaching_profile = next(
        (
            profile
            for profile in list_research_profiles()
            if profile.key == "teaching_breakdown"
        ),
        None,
    )
    teaching_required = {"课程章节建议", "关键代码讲解顺序", "练习任务"}
    teaching_missing = (
        sorted(teaching_required - set(teaching_profile.report_sections))
        if teaching_profile is not None
        else sorted(teaching_required)
    )
    passed = (
        not missing_static_sections
        and not profiles_without_sections
        and not teaching_missing
    )
    messages = []
    if missing_static_sections:
        messages.append(
            f"缺少 profile-aware 固定章节: {', '.join(missing_static_sections)}"
        )
    if profiles_without_sections:
        messages.append(
            f"以下调研档位缺少动态报告章节: {', '.join(profiles_without_sections)}"
        )
    if teaching_missing:
        messages.append(f"教学拆解档位缺少章节: {', '.join(teaching_missing)}")
    return _check(
        "profile_aware_report_sections",
        passed,
        "调研档位和资料包摘要报告护栏已启用。" if passed else "；".join(messages),
    )


def _evaluate_scan_case(case: EvaluationCase, scan_result: dict) -> dict:
    """根据 fixture 类型检查只读扫描结果，并返回统一 case 结果。

    扫描类用例只验证确定性能力：文件是否进入 file_tree、入口是否识别、
    README 是否存在，以及敏感路径是否只记录在 skipped_items。它们不调用 LLM，
    也不评价真实仓库的调研质量。
    """

    # file_tree 同时包含目录和文件，后续判断实际扫描文件时需要过滤 kind。
    file_paths = {
        item["path"] for item in scan_result["file_tree"] if item.get("kind") == "file"
    }
    skipped_paths = {item["path"] for item in scan_result["skipped_items"]}

    if case.case_id == "healthy-small":
        checks = [
            _check(
                "readme_present",
                scan_result["readme_excerpt"] is not None,
                "README 摘要已形成基础证据线索。",
            ),
            _check(
                "files_scanned",
                {"README.md", "app.py", "pyproject.toml"} <= file_paths,
                "扫描结果包含 README、入口文件和项目标记。",
            ),
            _check(
                "entrypoint_detected",
                "app.py" in scan_result["entrypoint_files"],
                "入口文件 app.py 被识别。",
            ),
        ]
    elif case.case_id == "missing-docs":
        checks = [
            _check(
                "readme_missing_detected",
                scan_result["readme_excerpt"] is None,
                "缺少 README 被记录为可验证发现，不导致 harness 失败。",
            ),
            _check(
                "files_scanned",
                "app.py" in file_paths and scan_result["metadata"]["total_files"] == 1,
                "即使没有 README，代码文件仍可被扫描。",
            ),
        ]
    elif case.case_id == "sensitive-skip":
        checks = [
            _check(
                "env_skipped",
                ".env" in skipped_paths,
                ".env 被敏感路径策略捕获到 skipped_items。",
            ),
            _check(
                "env_not_in_file_tree",
                ".env" not in file_paths,
                ".env 没有进入 file_tree，避免把敏感文件作为证据展开。",
            ),
            _check(
                "readme_present",
                scan_result["readme_excerpt"] is not None,
                "普通 README 仍可被读取。",
            ),
        ]
    else:
        checks = [
            _check(
                "known_case",
                False,
                f"未知 evaluation case: {case.case_id}",
            )
        ]

    checks.append(_project_research_package_check())
    checks.append(_profile_aware_report_check())

    expected_check_names = set(case.expected_checks)
    actual_check_names = {check["name"] for check in checks}
    missing_checks = sorted(expected_check_names - actual_check_names)
    unexpected_checks = sorted(actual_check_names - expected_check_names)
    # 某个 check 通过但名称被意外改写时，仍应视为契约回归，因此同时比较名称集合。
    check_names_match = not missing_checks and not unexpected_checks

    return {
        "case_id": case.case_id,
        "description": case.description,
        "case_type": case.case_type,
        "passed": all(check["passed"] for check in checks) and check_names_match,
        "expected_checks": case.expected_checks,
        "missing_checks": missing_checks,
        "unexpected_checks": unexpected_checks,
        "checks": checks,
    }


def build_summary(results: list[dict]) -> dict:
    """汇总总数、case_type 维度和调研 profile 维度的通过/失败数量。

    同一份结果会同时用于总览和前端分组展示；这里只聚合，不修改原始 case 结果。
    """

    passed = sum(1 for result in results if result["passed"])
    failed = len(results) - passed
    by_type: dict[str, dict[str, int]] = {}
    profiles: dict[str, dict[str, int]] = {}
    for result in results:
        case_type = result.get("case_type", "unknown")
        by_type.setdefault(case_type, {"total": 0, "passed": 0, "failed": 0})
        by_type[case_type]["total"] += 1
        by_type[case_type]["passed" if result["passed"] else "failed"] += 1
        profile = result.get("research_profile")
        if isinstance(profile, dict) and profile.get("key"):
            key = profile["key"]
            profiles.setdefault(key, {"total": 0, "passed": 0, "failed": 0})
            profiles[key]["total"] += 1
            profiles[key]["passed" if result["passed"] else "failed"] += 1
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "by_type": by_type,
        "profiles": profiles,
    }


def run_evaluations(
    session: Session, *, workspace_root: Path | None = None
) -> EvaluationRun:
    """运行全部评估用例，并持久化一条 ``EvaluationRun``。

    ``workspace_root`` 只用于测试或需要保留 fixture 的调试场景。正常 API 调用
    不传该参数时会创建临时目录，评估结束后自动清理，避免 fixture 污染正式
    workspace。
    """

    workspace_context = (
        nullcontext(workspace_root)
        if workspace_root is not None
        else TemporaryDirectory(prefix="loop-evaluations-")
    )

    with workspace_context as active_workspace:
        # TemporaryDirectory/nullcontext 都返回可直接转成 Path 的路径，后续逻辑无需区分来源。
        root = Path(active_workspace).resolve()
        return _run_evaluations_in_workspace(session, root)


def _run_evaluations_in_workspace(session: Session, root: Path) -> EvaluationRun:
    """在给定工作区中执行 case 循环，并写入最终评估状态。

    先创建 ``running`` 记录并 flush，再执行用例。全部用例结束后一次性写入
    summary、case results、终态和完成时间，最后 commit。若用例代码抛异常，
    由调用方的事务边界负责回滚。
    """

    root.mkdir(parents=True, exist_ok=True)

    run = EvaluationRun(status="running", summary_json={}, case_results_json=[])
    session.add(run)
    session.flush()

    results = []
    for case in evaluation_cases():
        # 配置层出现未知类型时保留该 case 的失败结果，继续评估其余用例。
        if case.case_type not in KNOWN_CASE_TYPES:
            results.append(_unknown_case_type_result(case))
            continue

        # 每次运行都重建 fixture，保证 case 输入稳定，不被上一次本地运行污染。
        case_root = write_case_repo(root, case)
        scan_result = _scan_case(case_root)
        if case.case_type == "scan_regression":
            # 扫描回归只检查文件级事实，不构造完整 Analysis Package。
            results.append(_evaluate_scan_case(case, scan_result))
        else:
            # profile benchmark 会继续执行质量评分、verifier 和报告章节校验。
            results.append(evaluate_profile_benchmark(case, scan_result))

    run.summary_json = build_summary(results)
    run.case_results_json = results
    # 任一 case 失败都会把整次评估标记为 failed，便于 CI 和页面快速判断。
    run.status = "succeeded" if run.summary_json["failed"] == 0 else "failed"
    run.completed_at = utc_now()

    session.commit()
    session.refresh(run)
    return run
