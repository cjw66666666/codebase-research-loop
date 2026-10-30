
"""Loop Assistant 的 FastAPI 路由包。

各 ``routes_*`` 模块只负责 HTTP 参数接收、资源存在性检查和事务边界；具体业务
编排放在 ``app.services``、``app.engine`` 等模块中。
"""
