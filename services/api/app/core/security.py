"""输入源结构校验和规范化。

该模块只检查来源类型、URL 结构和本地路径是否存在，不读取文件内容、不扫描
目录、不访问网络，也不是认证授权模块。网络访问和路径读取仍需由对应采集工具
继续执行边界控制。
"""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class SourceValidationError(ValueError):
    """输入源格式或本地路径不满足采集前置条件。"""

    pass


@dataclass(frozen=True)
class ValidatedSource:
    """规范化后的输入源位置及其可审计元数据。"""

    # normalized_uri 用于去重和后续采集；metadata 只保存可公开的来源描述。
    normalized_uri: str
    metadata: dict[str, str]


# 当前 API 明确支持的来源类型；未知类型应在写入数据库前拒绝。
SUPPORTED_SOURCE_TYPES = {"web_url", "local_file", "local_directory", "github_repo"}


def validate_source_input(source_type: str, uri: str) -> ValidatedSource:
    """校验并通过对应规则规范化一个输入源。

    该函数仅做结构和本地文件系统属性检查，不读取内容、不扫描目录，也不请求
    URL。所有校验错误统一转为 SourceValidationError，供 API 映射为 400。
    """

    # 先收窄来源类型，避免调用方把任意 URI 交给未预期的解析分支。
    if source_type not in SUPPORTED_SOURCE_TYPES:
        raise SourceValidationError(f"Unsupported source type: {source_type}")

    # 保留用户原始值用于审计，实际校验和规范化使用去除首尾空白后的值。
    trimmed_uri = uri.strip()
    if not trimmed_uri:
        raise SourceValidationError("Source uri cannot be empty")

    if source_type == "web_url":
        return _validate_web_url(trimmed_uri)
    if source_type == "github_repo":
        return _validate_github_repo(trimmed_uri)
    if source_type == "local_file":
        return _validate_local_path(trimmed_uri, expected_kind="file")
    # 通过前面类型白名单后，剩余类型只有 local_directory。
    return _validate_local_path(trimmed_uri, expected_kind="directory")


def _validate_web_url(uri: str) -> ValidatedSource:
    """校验普通网页地址，并提取协议、主机和端口元数据。"""

    parsed = urlparse(uri)
    # 仅允许 HTTP(S)，且必须有主机名；这里不解析 DNS，也不判断公网/内网地址。
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SourceValidationError("web_url must be an http or https URL")
    # 禁止在 URL 中携带用户名或密码，避免凭据进入数据库、日志和审计事件。
    if parsed.username or parsed.password:
        raise SourceValidationError("web_url must not contain user credentials")

    metadata = {"scheme": parsed.scheme, "host": parsed.hostname}
    try:
        # 访问 parsed.port 才会触发端口格式校验；非法端口需要转换成领域错误。
        port = parsed.port
    except ValueError as exc:
        raise SourceValidationError("web_url contains an invalid port") from exc
    if port is not None:
        metadata["port"] = str(port)

    return ValidatedSource(
        normalized_uri=uri,
        metadata=metadata,
    )


def _validate_github_repo(uri: str) -> ValidatedSource:
    """校验严格的 GitHub 仓库地址，并生成去掉 .git 后缀的规范 URL。"""

    parsed = urlparse(uri)
    try:
        # 提前读取端口以捕获非法数字，后续再统一拒绝 GitHub 地址显式端口。
        port = parsed.port
    except ValueError as exc:
        raise SourceValidationError("github_repo contains an invalid port") from exc

    path_parts = [part for part in parsed.path.strip("/").split("/") if part]
    # 只接受 https://github.com/<owner>/<repo>，拒绝凭据、查询参数、片段和额外路径。
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or port is not None
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or len(path_parts) != 2
    ):
        raise SourceValidationError("github_repo must be an https://github.com/<owner>/<repo> URL")

    # 用户常粘贴 .git 克隆地址；这里统一为网页仓库地址，便于去重和后续采集。
    repo = _remove_git_suffix(path_parts[1])
    if not repo:
        raise SourceValidationError("github_repo must include a repository name")

    normalized = f"https://github.com/{path_parts[0]}/{repo}"
    return ValidatedSource(
        normalized_uri=normalized,
        metadata={
            "scheme": "https",
            "host": "github.com",
            "owner": path_parts[0],
            "repo": repo,
        },
    )


def _remove_git_suffix(repo: str) -> str:
    """大小写不敏感地移除仓库名末尾的 .git。"""

    if repo.lower().endswith(".git"):
        return repo[:-4]
    return repo


def _validate_local_path(uri: str, expected_kind: str) -> ValidatedSource:
    """把本地路径解析为绝对路径，并检查其存在性和文件类型。"""

    # resolve() 会展开 ~、转成绝对路径并解析符号链接；这里不读取目标内容。
    path = Path(uri).expanduser().resolve()
    if not path.exists():
        raise SourceValidationError(f"Local path does not exist: {path}")
    if expected_kind == "file" and not path.is_file():
        raise SourceValidationError(f"Expected a local file: {path}")
    if expected_kind == "directory" and not path.is_dir():
        raise SourceValidationError(f"Expected a local directory: {path}")
    # 该函数不限制路径必须位于 workspace 内；实际读取工具仍需执行路径策略校验。
    return ValidatedSource(
        normalized_uri=str(path),
        metadata={"kind": expected_kind},
    )
