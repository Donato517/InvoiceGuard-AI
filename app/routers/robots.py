"""
模組名稱：app.routers.robots
功能說明：提供 /robots.txt，告訴搜尋引擎可索引的範圍。
路由：GET /robots.txt
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["robots"])

# 前台開放索引；需登入的頁面本身會導向登入頁，不會被收錄內容
ROBOTS_TXT = "User-agent: *\nAllow: /\n"


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt() -> str:
    """回傳 robots.txt 內容。"""
    return ROBOTS_TXT
