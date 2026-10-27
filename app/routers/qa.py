"""
模組名稱：app.routers.qa
功能說明：智慧問答輔助——提供問答對話介面與部門知識庫來源選取。
路由：/qa
注意事項：
    - 此功能需登入。
    - 支援 HTMX 提問串接與勾選知識庫即時更新。
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.deps import AccessToken
from app.core.templating import templates

router = APIRouter(prefix="/qa", tags=["qa"])

# 初始示範對話紀錄
_CHAT_HISTORY: list[dict[str, str | list[str]]] = [
    {
        "role": "assistant",
        "text": "您好！我是 InvoiceGuard AI 智慧問答助手。您可以詢問發票營業稅法規、進項扣抵資格、申報檔格式或會計傳票分錄等問題。",
        "sources": ["營業稅相關規定"],
    }
]

# 示範知識庫配置
_USER_KBS: list[dict[str, str | bool]] = [
    {"assignment_id": "tax", "title": "營業稅相關規定", "selected": True},
    {"assignment_id": "format", "title": "進項申報檔格式說明", "selected": True},
    {"assignment_id": "deduction", "title": "進項扣抵判斷指引", "selected": False},
    {"assignment_id": "voucher", "title": "會計傳票作業手冊", "selected": True},
    {"assignment_id": "workflow", "title": "InvoiceGuard 操作說明", "selected": True},
]

QUICK_QUESTIONS: list[str] = [
    "三聯式發票申報期限？",
    "進項稅額哪些不可扣抵？",
    "如何產生格式 21 申報檔？",
    "會計傳票分錄如何借貸平衡？",
]


@router.get("", response_class=HTMLResponse)
async def qa_page(request: Request, token: AccessToken) -> HTMLResponse:
    """問答輔助主頁面。"""
    return templates.TemplateResponse(
        request,
        "pages/qa/index.html",
        {
            "messages": _CHAT_HISTORY,
            "knowledge_bases": _USER_KBS,
            "quick_questions": QUICK_QUESTIONS,
        },
    )


@router.post("/ask", response_class=HTMLResponse)
async def ask_question(
    request: Request,
    token: AccessToken,
    question: Annotated[str, Form()],
) -> HTMLResponse:
    """送出問題並取得回答（HTMX 局部替換 chat-messages）。"""
    q_clean = question.strip()
    if q_clean:
        _CHAT_HISTORY.append({"role": "user", "text": q_clean, "sources": []})

        # 模擬問答回答
        answer = f"依據選用之知識庫，「{q_clean}」：統一發票與營業稅申報請依加值型營業稅法及國稅局格式規定辦理，進項憑證須具備載有稅額與統編之合法憑證。"
        _CHAT_HISTORY.append(
            {"role": "assistant", "text": answer, "sources": ["營業稅相關規定", "進項扣抵判斷指引"]}
        )

    return templates.TemplateResponse(
        request,
        "pages/qa/_chat_messages.html",
        {"messages": _CHAT_HISTORY},
    )


@router.post("/clear")
async def clear_chat(token: AccessToken) -> RedirectResponse:
    """清除對話紀錄。"""
    global _CHAT_HISTORY
    _CHAT_HISTORY = [
        {
            "role": "assistant",
            "text": "對話已重設。您可以再次提問任何發票或稅務問題。",
            "sources": [],
        }
    ]
    return RedirectResponse("/qa", status_code=303)


@router.post("/sources", response_class=HTMLResponse)
async def update_sources(
    request: Request,
    token: AccessToken,
    source_ids: Annotated[list[str] | None, Form()] = None,
) -> HTMLResponse:
    """勾選/取消問答知識庫來源（HTMX 局部替換 source-picker）。"""
    selected_ids = source_ids or []
    for kb in _USER_KBS:
        kb["selected"] = kb["assignment_id"] in selected_ids

    return templates.TemplateResponse(
        request,
        "pages/qa/_source_picker.html",
        {"knowledge_bases": _USER_KBS},
    )
