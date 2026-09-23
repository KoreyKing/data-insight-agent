"""请求体边界校验（architecture.md §2）：拦截无法以 UTF-8 编码的字符串。

JSON 允许 `\\uD800`-`\\uDFFF` 转义出孤立代理项，解码所得 str 无法再编码回 UTF-8。
放行后它会一路走到 SQLite 绑定参数或响应序列化才炸，对外表现为 500。

逐字段校验在这里不成立：`POST /reports/run` 的 `task` 是开放式字典合并，字段无法穷举。
因此统一在进入业务处理前扫描整个请求体，字段级校验（如 title 长度）保持不变、各司其职。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

JSON_MEDIA_TYPE = "application/json"
REQUEST_BODY_INVALID = "REQUEST_BODY_INVALID"
INVALID_BODY_MESSAGE = "请求内容包含无法处理的字符，请检查后重试。"


class RequestBodyInvalid(Exception):
    """请求体含无法以 UTF-8 落库或回传的字符。"""


async def reject_unencodable_body(request: Request) -> None:
    """挂在 api_router 上：每个 /api/v1/* 请求进入业务处理前先过这一关。"""
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != JSON_MEDIA_TYPE:
        # 上传走 multipart，不读取也不解析其 body。
        return
    # Starlette 把 body 缓存在同一个 Request 上，FastAPI 随后解析参数时复用，不会二次读流。
    body = await request.body()
    if not body:
        return
    try:
        payload = json.loads(body)
    except ValueError:
        # 非法 JSON 交给 FastAPI 自己回 422，这里不抢答。
        return
    if contains_unencodable(payload):
        raise RequestBodyInvalid


def contains_unencodable(payload: Any) -> bool:
    """迭代遍历（非递归）：深层嵌套的请求体不会把校验本身压爆栈。字典键与值同查。"""
    stack: list[Any] = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return True
        elif isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return False


async def request_body_invalid_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": REQUEST_BODY_INVALID, "message": INVALID_BODY_MESSAGE},
    )
