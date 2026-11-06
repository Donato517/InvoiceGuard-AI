"""
模組名稱：app.utils.app_nav
功能說明：前台登入後的側欄群組與手機底部分頁項目（2026-11-06 對齊後台），並判斷目前頁面屬於哪一項。
注意事項：
    - 前台沒有部門功能權限，項目固定；登入後才顯示（layouts/default.html）。
    - 目前頁面取「路徑最長的相符項目」：/invoices/upload 屬於「上傳發票」，不會同時點亮「我的發票」。
    - 手機底部分頁的「拍照上傳」也涵蓋電腦上傳頁，讓上傳流程中分頁標示一致。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    """一個導覽項目；match 為歸屬於此項目的路徑前綴（第一個是連結位址）。"""

    name: str
    icon: str
    match: tuple[str, ...]
    active: bool = False

    @property
    def route(self) -> str:
        """連結位址。"""
        return self.match[0]


@dataclass(frozen=True)
class NavGroup:
    """側欄群組；current 表示目前頁面在這個群組內（預設展開）。"""

    key: str
    title: str
    icon: str
    items: tuple[NavItem, ...]
    current: bool = False


_SIDEBAR: tuple[tuple[str, str, str, tuple[NavItem, ...]], ...] = (
    (
        "invoice",
        "發票作業",
        "🧾",
        (
            NavItem("上傳發票", "📤", ("/invoices/upload",)),
            NavItem("拍照上傳", "📷", ("/invoices/mobile-upload",)),
            NavItem("我的發票", "📄", ("/invoices",)),
            NavItem("範例發票參考", "🔍", ("/invoices/showcase-reference",)),
        ),
    ),
    ("rag", "RAG 知識庫", "📚", (NavItem("知識庫問答", "💬", ("/qa",)),)),
)

_TABS: tuple[NavItem, ...] = (
    NavItem("拍照上傳", "📷", ("/invoices/mobile-upload", "/invoices/upload")),
    NavItem("我的發票", "📄", ("/invoices",)),
    NavItem("問答", "💬", ("/qa",)),
)


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def _active_item(path: str, items: list[NavItem]) -> NavItem | None:
    """路徑最長的相符項目；都不相符時回傳 None。"""
    best: tuple[int, NavItem] | None = None
    for item in items:
        for prefix in item.match:
            if _matches(path, prefix) and (best is None or len(prefix) > best[0]):
                best = (len(prefix), item)
    return best[1] if best else None


def _with_active(item: NavItem, active: NavItem | None) -> NavItem:
    return NavItem(item.name, item.icon, item.match, active=item is active)


def sidebar_groups(path: str) -> list[NavGroup]:
    """側欄群組與項目，標示目前頁面（目前頁面所在群組 current=True）。

    Args:
        path: 目前請求的路徑，例如 "/invoices/upload"。

    Returns:
        list[NavGroup]: 依固定順序排列的群組。
    """
    active = _active_item(path, [item for *_, items in _SIDEBAR for item in items])
    groups = []
    for key, title, icon, items in _SIDEBAR:
        marked = tuple(_with_active(item, active) for item in items)
        groups.append(NavGroup(key, title, icon, marked, current=any(i.active for i in marked)))
    return groups


def tab_items(path: str) -> list[NavItem]:
    """手機底部分頁，標示目前頁面。

    Args:
        path: 目前請求的路徑。

    Returns:
        list[NavItem]: 拍照上傳、我的發票、問答。
    """
    active = _active_item(path, list(_TABS))
    return [_with_active(item, active) for item in _TABS]
