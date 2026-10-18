# 验证记录

记录日期：2026-10-18。

## 后端测试

在 `services/api` 下执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

结果：

```text
268 passed, 1 skipped, 1 warning in 21.99s
```

## 数据库迁移与表

- Alembic 迁移文件：14 个。
- SQLAlchemy 业务表定义：27 张。
- 另有 Alembic 自身的版本表，不计入业务表。

## 自调研产物

- LangGraph 节点数：9。
- 报告正文长度：16,418 字符。
- 确定性校验项：9 项。
- 质量分：97。
- LLM 分析与 LLM 复核状态：失败后回退到确定性分析，不影响主链路。

## 评估用例

- 总数：8。
- 扫描回归：3。
- 调研档位 fixture：5。
- 全部通过。

评估用例用于结构回归，不等同于真实仓库效果评测。

