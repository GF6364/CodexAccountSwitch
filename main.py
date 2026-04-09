from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, W, Y, messagebox
import tkinter as tk
from tkinter import ttk
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest


SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SCRIPT_DIR
STATE_PATH = APP_DIR / "switcher_state.json"
DEFAULT_AUTH_FILE = Path.home() / ".codex" / "auth.json"
DEFAULT_STORAGE_DIR = APP_DIR / "auth_store"
SNAPSHOT_INDEX_NAME = "snapshots.json"
CHATGPT_BASE_URL = "https://chatgpt.com/backend-api"


@dataclass
class SnapshotRecord:
    snapshot_id: str
    file_name: str
    saved_at: str
    email: str
    display_name: str
    plan: str
    auth_provider: str
    account_id: str
    last_refresh: str
    quota_used_percent: float | None = None
    quota_reset_at: int | None = None


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_state() -> dict[str, Any]:
    return load_json(STATE_PATH, {"last_snapshot_id": "", "last_restored_at": ""})


def save_state(snapshot: SnapshotRecord) -> None:
    save_json(
        STATE_PATH,
        {
            "last_snapshot_id": snapshot.snapshot_id,
            "last_restored_at": datetime.now().isoformat(timespec="seconds"),
        },
    )


def resolve_auth_file() -> Path:
    return DEFAULT_AUTH_FILE.expanduser()


def resolve_storage_dir() -> Path:
    return DEFAULT_STORAGE_DIR


def resolve_snapshot_index_path() -> Path:
    return resolve_storage_dir() / SNAPSHOT_INDEX_NAME


def decode_jwt_payload(token: str | None) -> dict[str, Any]:
    if not token or token.count(".") < 2:
        return {}

    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


def parse_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_auth_metadata(data: dict[str, Any]) -> dict[str, str]:
    tokens = data.get("tokens") or {}
    id_payload = decode_jwt_payload(tokens.get("id_token"))
    access_payload = decode_jwt_payload(tokens.get("access_token"))
    auth_payload = id_payload.get("https://api.openai.com/auth") or access_payload.get("https://api.openai.com/auth") or {}
    profile_payload = access_payload.get("https://api.openai.com/profile") or {}

    return {
        "email": str(id_payload.get("email") or profile_payload.get("email") or ""),
        "display_name": str(id_payload.get("name") or ""),
        "plan": str(auth_payload.get("chatgpt_plan_type") or ""),
        "account_id": str(tokens.get("account_id") or auth_payload.get("chatgpt_account_id") or ""),
        "auth_provider": str(id_payload.get("auth_provider") or ""),
        "last_refresh": str(data.get("last_refresh") or ""),
    }


def read_auth_data(path: Path) -> dict[str, Any]:
    return load_json(path, {})


def read_auth_metadata(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return extract_auth_metadata(read_auth_data(path))


def read_auth_tokens(path: Path) -> dict[str, Any]:
    data = read_auth_data(path)
    tokens = data.get("tokens") or {}
    if not isinstance(tokens, dict):
        return {}
    return tokens


def is_logged_in_auth(metadata: dict[str, str], tokens: dict[str, Any]) -> bool:
    has_identity = bool(metadata.get("account_id") or metadata.get("email"))
    has_token = bool(tokens.get("access_token") or tokens.get("id_token"))
    return has_identity and has_token


def require_logged_in_metadata(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"当前 Codex 认证文件不存在: {path}")

    metadata = read_auth_metadata(path)
    tokens = read_auth_tokens(path)
    if not is_logged_in_auth(metadata, tokens):
        raise RuntimeError("当前未检测到已登录的 Codex 账号。")
    return metadata


def backup_live_auth(auth_file: Path) -> Path | None:
    if not auth_file.exists():
        return None

    backup_dir = APP_DIR / "backups"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"auth-{timestamp}.json"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(auth_file, backup_path)
    return backup_path


def record_from_dict(item: dict[str, Any]) -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_id=str(item.get("snapshot_id") or ""),
        file_name=str(item.get("file_name") or ""),
        saved_at=str(item.get("saved_at") or ""),
        email=str(item.get("email") or ""),
        display_name=str(item.get("display_name") or ""),
        plan=str(item.get("plan") or ""),
        auth_provider=str(item.get("auth_provider") or ""),
        account_id=str(item.get("account_id") or ""),
        last_refresh=str(item.get("last_refresh") or ""),
        quota_used_percent=parse_optional_float(item.get("quota_used_percent")),
        quota_reset_at=parse_optional_int(item.get("quota_reset_at")),
    )


def record_to_dict(record: SnapshotRecord) -> dict[str, Any]:
    return {
        "snapshot_id": record.snapshot_id,
        "file_name": record.file_name,
        "saved_at": record.saved_at,
        "email": record.email,
        "display_name": record.display_name,
        "plan": record.plan,
        "auth_provider": record.auth_provider,
        "account_id": record.account_id,
        "last_refresh": record.last_refresh,
        "quota_used_percent": record.quota_used_percent,
        "quota_reset_at": record.quota_reset_at,
    }


def load_snapshot_records() -> list[SnapshotRecord]:
    storage_dir = resolve_storage_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    index_path = resolve_snapshot_index_path()
    raw_data = load_json(index_path, {"snapshots": []})
    records: list[SnapshotRecord] = []

    for item in raw_data.get("snapshots", []):
        record = record_from_dict(item)
        snapshot_path = storage_dir / record.file_name
        if record.snapshot_id and record.file_name and snapshot_path.exists():
            records.append(record)

    records.sort(key=lambda item: item.saved_at, reverse=True)
    return records


def save_snapshot_records(records: list[SnapshotRecord]) -> None:
    index_path = resolve_snapshot_index_path()
    save_json(index_path, {"snapshots": [record_to_dict(record) for record in records]})


def build_snapshot_record(metadata: dict[str, str], file_name: str) -> SnapshotRecord:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snapshot_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return SnapshotRecord(
        snapshot_id=snapshot_id,
        file_name=file_name,
        saved_at=timestamp,
        email=metadata.get("email", ""),
        display_name=metadata.get("display_name", ""),
        plan=metadata.get("plan", ""),
        auth_provider=metadata.get("auth_provider", ""),
        account_id=metadata.get("account_id", ""),
        last_refresh=metadata.get("last_refresh", ""),
    )


def update_snapshot_record(record: SnapshotRecord, metadata: dict[str, str]) -> SnapshotRecord:
    return SnapshotRecord(
        snapshot_id=record.snapshot_id,
        file_name=record.file_name,
        saved_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        email=metadata.get("email", ""),
        display_name=metadata.get("display_name", ""),
        plan=metadata.get("plan", ""),
        auth_provider=metadata.get("auth_provider", ""),
        account_id=metadata.get("account_id", ""),
        last_refresh=metadata.get("last_refresh", ""),
        quota_used_percent=record.quota_used_percent,
        quota_reset_at=record.quota_reset_at,
    )


def get_current_auth_summary() -> dict[str, str]:
    auth_file = resolve_auth_file()
    if not auth_file.exists():
        raise FileNotFoundError(f"当前 Codex 认证文件不存在: {auth_file}")
    return read_auth_metadata(auth_file)


def capture_current_snapshot() -> SnapshotRecord:
    auth_file = resolve_auth_file()

    storage_dir = resolve_storage_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)

    metadata = require_logged_in_metadata(auth_file)
    records = load_snapshot_records()
    account_id = metadata.get("account_id", "")

    if account_id:
        matching_records = [record for record in records if record.account_id == account_id]
    else:
        matching_records = []

    if matching_records:
        record = update_snapshot_record(matching_records[0], metadata)
        snapshot_path = storage_dir / record.file_name
        shutil.copy2(auth_file, snapshot_path)

        duplicate_ids = {item.snapshot_id for item in matching_records[1:]}
        for duplicate in matching_records[1:]:
            duplicate_path = storage_dir / duplicate.file_name
            if duplicate_path.exists():
                duplicate_path.unlink()

        updated_records: list[SnapshotRecord] = [record]
        for existing in records:
            if existing.snapshot_id == record.snapshot_id:
                continue
            if existing.snapshot_id in duplicate_ids:
                continue
            updated_records.append(existing)
        records = updated_records
    else:
        file_name = f"snapshot-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
        snapshot_path = storage_dir / file_name
        shutil.copy2(auth_file, snapshot_path)
        record = build_snapshot_record(metadata, file_name)
        records.insert(0, record)

    save_snapshot_records(records)
    return record


def find_snapshot_by_id(snapshot_id: str) -> SnapshotRecord:
    for record in load_snapshot_records():
        if record.snapshot_id == snapshot_id:
            return record
    raise ValueError("未找到所选快照")


def restore_snapshot(snapshot_id: str) -> tuple[SnapshotRecord, Path | None]:
    record = find_snapshot_by_id(snapshot_id)
    storage_dir = resolve_storage_dir()
    snapshot_path = storage_dir / record.file_name
    if not snapshot_path.exists():
        raise FileNotFoundError(f"快照文件不存在: {snapshot_path}")

    auth_file = resolve_auth_file()
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_live_auth(auth_file)
    shutil.copy2(snapshot_path, auth_file)
    save_state(record)
    return record, backup_path


def delete_snapshot(snapshot_id: str) -> SnapshotRecord:
    record = find_snapshot_by_id(snapshot_id)
    storage_dir = resolve_storage_dir()
    snapshot_path = storage_dir / record.file_name
    if snapshot_path.exists():
        snapshot_path.unlink()

    records = [item for item in load_snapshot_records() if item.snapshot_id != snapshot_id]
    save_snapshot_records(records)
    return record


def format_summary(metadata: dict[str, str]) -> str:
    parts = []
    if metadata.get("email"):
        parts.append(f"邮箱: {metadata['email']}")
    if metadata.get("display_name"):
        parts.append(f"昵称: {metadata['display_name']}")
    if metadata.get("plan"):
        parts.append(f"套餐: {metadata['plan']}")
    if metadata.get("auth_provider"):
        parts.append(f"登录方式: {metadata['auth_provider']}")
    if metadata.get("account_id"):
        parts.append(f"账号ID: {metadata['account_id']}")
    if metadata.get("last_refresh"):
        parts.append(f"刷新时间: {metadata['last_refresh']}")
    return " | ".join(parts) if parts else "当前没有可解析的登录信息"


def get_remaining_quota_percent(record: SnapshotRecord) -> float | None:
    if record.quota_used_percent is None:
        return None

    remaining = 100 - record.quota_used_percent
    if remaining < 0:
        return 0.0
    if remaining > 100:
        return 100.0
    return remaining


def format_percent(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return f"{int(value)}%"
    return f"{value:.1f}%"


def format_quota_remaining(record: SnapshotRecord) -> str:
    return format_percent(get_remaining_quota_percent(record))


def format_quota_countdown(record: SnapshotRecord) -> str:
    if not record.quota_reset_at:
        return ""

    remaining_seconds = record.quota_reset_at - int(datetime.now().timestamp())
    if remaining_seconds <= 0:
        return "已刷新"
    return format_duration(remaining_seconds)


def format_reset_time(timestamp: int | None) -> str:
    if not timestamp:
        return "未知"
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(timestamp)


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "未知"

    if seconds < 60:
        return f"{seconds}秒"

    minutes, remain_seconds = divmod(seconds, 60)
    hours, remain_minutes = divmod(minutes, 60)
    days, remain_hours = divmod(hours, 24)

    parts: list[str] = []
    if days:
        parts.append(f"{days}天")
    if remain_hours:
        parts.append(f"{remain_hours}小时")
    if remain_minutes:
        parts.append(f"{remain_minutes}分钟")
    if remain_seconds and not parts:
        parts.append(f"{remain_seconds}秒")
    return "".join(parts) or "0秒"


def request_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    req = urlrequest.Request(url, headers=headers)
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))

    try:
        with opener.open(req, timeout=30) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"请求额度接口失败: HTTP {exc.code} {payload[:300]}") from exc
    except Exception as exc:
        raise RuntimeError(f"请求额度接口失败: {exc}") from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"额度接口返回了非 JSON 数据: {payload[:300]}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("额度接口返回格式异常。")

    return data


def get_quota_for_auth_file(auth_file: Path) -> dict[str, Any]:
    tokens = read_auth_tokens(auth_file)
    access_token = str(tokens.get("access_token") or "")
    account_id = str(tokens.get("account_id") or "")
    if not access_token:
        raise RuntimeError("auth.json 中缺少 access_token，无法读取额度。")
    if not account_id:
        raise RuntimeError("auth.json 中缺少 account_id，无法读取额度。")

    headers = {
        "authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id,
        "accept": "application/json",
        "content-type": "application/json",
        "user-agent": "OpenAI/Codex",
    }
    return request_json(f"{CHATGPT_BASE_URL}/wham/usage", headers)


def get_current_quota() -> dict[str, Any]:
    auth_file = resolve_auth_file()
    if not auth_file.exists():
        raise FileNotFoundError(f"当前 Codex 认证文件不存在: {auth_file}")
    return get_quota_for_auth_file(auth_file)


def get_snapshot_quota(record: SnapshotRecord) -> dict[str, Any]:
    snapshot_path = resolve_storage_dir() / record.file_name
    if not snapshot_path.exists():
        raise FileNotFoundError(f"快照文件不存在: {snapshot_path}")
    return get_quota_for_auth_file(snapshot_path)


def apply_quota_to_record(record: SnapshotRecord, quota: dict[str, Any]) -> SnapshotRecord:
    rate_limit = quota.get("rate_limit") if isinstance(quota.get("rate_limit"), dict) else {}
    primary_window = rate_limit.get("primary_window") if isinstance(rate_limit.get("primary_window"), dict) else {}

    return SnapshotRecord(
        snapshot_id=record.snapshot_id,
        file_name=record.file_name,
        saved_at=record.saved_at,
        email=record.email,
        display_name=record.display_name,
        plan=record.plan,
        auth_provider=record.auth_provider,
        account_id=record.account_id,
        last_refresh=record.last_refresh,
        quota_used_percent=parse_optional_float(primary_window.get("used_percent")),
        quota_reset_at=parse_optional_int(primary_window.get("reset_at")),
    )


def update_local_quota_cache(account_id: str, quota: dict[str, Any]) -> bool:
    if not account_id:
        return False

    records = load_snapshot_records()
    updated = False
    new_records: list[SnapshotRecord] = []
    for record in records:
        if record.account_id == account_id:
            new_records.append(apply_quota_to_record(record, quota))
            updated = True
        else:
            new_records.append(record)

    if updated:
        save_snapshot_records(new_records)
    return updated


def build_window_summary(title: str, window: dict[str, Any] | None) -> str:
    if not window:
        return f"{title}: 无"

    used_percent = window.get("used_percent")
    window_seconds = window.get("limit_window_seconds")
    reset_after = window.get("reset_after_seconds")
    reset_at = window.get("reset_at")

    return (
        f"{title}: 已用 {used_percent if used_percent is not None else '未知'}%"
        f" | 周期 {format_duration(window_seconds if isinstance(window_seconds, int) else None)}"
        f" | 剩余 {format_duration(reset_after if isinstance(reset_after, int) else None)}"
        f" | 重置时间 {format_reset_time(reset_at if isinstance(reset_at, int) else None)}"
    )


def format_quota_summary(quota: dict[str, Any]) -> str:
    rate_limit = quota.get("rate_limit") if isinstance(quota.get("rate_limit"), dict) else {}
    review_limit = quota.get("code_review_rate_limit") if isinstance(quota.get("code_review_rate_limit"), dict) else {}
    credits = quota.get("credits") if isinstance(quota.get("credits"), dict) else {}
    spend_control = quota.get("spend_control") if isinstance(quota.get("spend_control"), dict) else {}

    lines = [
        f"邮箱: {quota.get('email') or '未知'}",
        f"套餐: {quota.get('plan_type') or '未知'}",
        f"普通额度可用: {'是' if rate_limit.get('allowed') else '否'} | 已触顶: {'是' if rate_limit.get('limit_reached') else '否'}",
        build_window_summary("普通额度窗口", rate_limit.get("primary_window") if isinstance(rate_limit.get("primary_window"), dict) else None),
        build_window_summary("代码审查额度窗口", review_limit.get("primary_window") if isinstance(review_limit.get("primary_window"), dict) else None),
        (
            "Credits: "
            f"has_credits={credits.get('has_credits')}"
            f" | unlimited={credits.get('unlimited')}"
            f" | balance={credits.get('balance') or '无'}"
        ),
        f"消费控制触发: {'是' if spend_control.get('reached') else '否'}",
    ]

    additional_limits = quota.get("additional_rate_limits")
    if isinstance(additional_limits, list) and additional_limits:
        for item in additional_limits:
            if not isinstance(item, dict):
                continue
            limit_name = item.get("limit_name") or item.get("limit_id") or "其他额度"
            lines.append(
                build_window_summary(
                    f"附加额度 {limit_name}",
                    item.get("primary_window") if isinstance(item.get("primary_window"), dict) else None,
                )
            )

    promo = quota.get("promo")
    if promo:
        lines.append(f"提示: {promo}")

    return "\n".join(lines)


def print_snapshot_list() -> None:
    records = load_snapshot_records()
    if not records:
        print("还没有保存任何登录快照。")
        return

    for index, record in enumerate(records, start=1):
        print(
            f"{index}. [{record.snapshot_id}] {record.email or '未知邮箱'} | "
            f"{record.display_name or '未知昵称'} | {record.plan or '未知套餐'} | "
            f"{record.auth_provider or '未知方式'} | {record.saved_at}"
        )


class CodexSwitcherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.records: list[SnapshotRecord] = []

        self.root.title("Codex 账号切换器")
        self.root.geometry("980x620")
        self.root.minsize(900, 560)

        self.current_summary_var = tk.StringVar(value="正在读取当前登录信息...")
        self.status_var = tk.StringVar(value="就绪")

        self.build_ui()
        self.refresh_current_summary()
        self.refresh_snapshot_list()

    def build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=BOTH, expand=True)

        current_frame = ttk.LabelFrame(container, text="当前 Codex 登录态", padding=12)
        current_frame.pack(fill="x")

        summary_label = ttk.Label(current_frame, textvariable=self.current_summary_var, justify=LEFT, wraplength=900)
        summary_label.pack(fill="x", anchor=W)

        current_actions = ttk.Frame(current_frame)
        current_actions.pack(fill="x", pady=(10, 0))

        ttk.Button(current_actions, text="保存当前登录数据", command=self.save_current_snapshot).pack(side=LEFT)
        ttk.Button(current_actions, text="刷新当前信息", command=self.refresh_current_summary).pack(side=LEFT, padx=(10, 0))
        ttk.Button(current_actions, text="获取当前额度", command=self.fetch_current_quota).pack(side=LEFT, padx=(10, 0))

        list_frame = ttk.LabelFrame(container, text="已保存的登录数据", padding=12)
        list_frame.pack(fill=BOTH, expand=True, pady=(12, 0))

        columns = ("email", "display_name", "plan", "provider", "quota_remaining", "quota_countdown", "saved_at")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=10)
        self.tree.heading("email", text="邮箱")
        self.tree.heading("display_name", text="昵称")
        self.tree.heading("plan", text="套餐")
        self.tree.heading("provider", text="登录方式")
        self.tree.heading("quota_remaining", text="剩余额度")
        self.tree.heading("quota_countdown", text="刷新倒计时")
        self.tree.heading("saved_at", text="保存时间")

        self.tree.column("email", width=220, anchor=W)
        self.tree.column("display_name", width=100, anchor=W)
        self.tree.column("plan", width=80, anchor=W)
        self.tree.column("provider", width=90, anchor=W)
        self.tree.column("quota_remaining", width=90, anchor=W)
        self.tree.column("quota_countdown", width=120, anchor=W)
        self.tree.column("saved_at", width=150, anchor=W)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Button-3>", self.on_tree_right_click)

        scrollbar = ttk.Scrollbar(list_frame, orient=VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="还原", command=self.restore_selected_snapshot)
        self.context_menu.add_command(label="获取额度", command=self.fetch_selected_snapshot_quota)
        self.context_menu.add_command(label="删除", command=self.delete_selected_snapshot)

        detail_frame = ttk.LabelFrame(container, text="选中项详情", padding=12)
        detail_frame.pack(fill="x", pady=(12, 0))

        self.detail_text = tk.Text(detail_frame, height=6, wrap="word")
        self.detail_text.pack(fill="x")
        self.detail_text.configure(state="disabled")

        bottom_actions = ttk.Frame(container)
        bottom_actions.pack(fill="x", pady=(12, 0))

        ttk.Button(bottom_actions, text="还原选中数据", command=self.restore_selected_snapshot).pack(side=LEFT)
        ttk.Button(bottom_actions, text="刷新列表", command=self.refresh_snapshot_list).pack(side=LEFT, padx=(10, 0))
        ttk.Label(bottom_actions, textvariable=self.status_var).pack(side=RIGHT)

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def refresh_current_summary(self) -> dict[str, str] | None:
        auth_file = resolve_auth_file()
        try:
            if not auth_file.exists():
                self.current_summary_var.set("当前未登录")
                self.set_status("未检测到当前登录")
                return None

            summary = get_current_auth_summary()
            tokens = read_auth_tokens(auth_file)
            if not is_logged_in_auth(summary, tokens):
                self.current_summary_var.set("当前未登录")
                self.set_status("未检测到当前登录")
                return None

            self.current_summary_var.set(format_summary(summary))
            self.set_status("已刷新当前登录信息")
            return summary
        except Exception as error:
            self.current_summary_var.set(f"读取失败: {error}")
            self.set_status("读取当前登录信息失败")
            return None

    def refresh_snapshot_list(self) -> None:
        self.records = load_snapshot_records()
        self.tree.delete(*self.tree.get_children())

        for record in self.records:
            self.tree.insert(
                "",
                END,
                iid=record.snapshot_id,
                values=(
                    record.email,
                    record.display_name,
                    record.plan,
                    record.auth_provider,
                    format_quota_remaining(record),
                    format_quota_countdown(record),
                    record.saved_at,
                ),
            )

        self.update_detail(None)
        self.set_status(f"已加载 {len(self.records)} 条保存数据")

    def get_selected_snapshot_id(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return str(selection[0])

    def update_detail(self, record: SnapshotRecord | None) -> None:
        if record is None:
            lines = ["请选择一条已保存的登录数据。"]
        else:
            lines = [
                f"邮箱: {record.email or '无'}",
                f"昵称: {record.display_name or '无'}",
                f"套餐: {record.plan or '无'}",
                f"登录方式: {record.auth_provider or '无'}",
                f"保存时间: {record.saved_at}",
                f"账号ID: {record.account_id or '无'}",
                f"刷新时间: {record.last_refresh or '无'}",
            ]
            if record.quota_used_percent is not None:
                lines.append(f"普通额度已用: {format_percent(record.quota_used_percent)}")
                lines.append(f"普通额度剩余: {format_quota_remaining(record) or '无'}")
                lines.append(f"刷新倒计时: {format_quota_countdown(record) or '无'}")
                lines.append(f"额度刷新时间: {format_reset_time(record.quota_reset_at) if record.quota_reset_at else '无'}")

        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", END)
        self.detail_text.insert("1.0", "\n".join(lines))
        self.detail_text.configure(state="disabled")

    def on_tree_select(self, _event: object) -> None:
        snapshot_id = self.get_selected_snapshot_id()
        if snapshot_id is None:
            self.update_detail(None)
            return

        for record in self.records:
            if record.snapshot_id == snapshot_id:
                self.update_detail(record)
                return

        self.update_detail(None)

    def on_tree_right_click(self, event: tk.Event[tk.Misc]) -> None:
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return

        self.tree.selection_set(item_id)
        self.tree.focus(item_id)
        self.on_tree_select(None)
        self.context_menu.tk_popup(event.x_root, event.y_root)
        self.context_menu.grab_release()

    def save_current_snapshot(self) -> None:
        summary = self.refresh_current_summary()
        if summary is None:
            messagebox.showwarning("提示", "当前未检测到已登录的 Codex 账号，无法保存空白数据。")
            self.set_status("未保存，当前未登录")
            return

        try:
            record = capture_current_snapshot()
        except Exception as error:
            messagebox.showerror("保存失败", str(error))
            self.set_status("保存失败")
            return

        self.refresh_current_summary()
        self.refresh_snapshot_list()
        self.tree.selection_set(record.snapshot_id)
        self.tree.focus(record.snapshot_id)
        self.on_tree_select(None)
        self.set_status(f"已保存: {record.email or record.snapshot_id}")
        messagebox.showinfo("保存成功", "已保存当前登录数据。")

    def fetch_current_quota(self) -> None:
        try:
            quota = get_current_quota()
            current_metadata = read_auth_metadata(resolve_auth_file())
            updated = update_local_quota_cache(current_metadata.get("account_id", ""), quota)
        except Exception as error:
            messagebox.showerror("获取额度失败", str(error))
            self.set_status("获取当前额度失败")
            return

        if updated:
            self.refresh_snapshot_list()
        self.set_status("已获取当前额度")
        messagebox.showinfo("当前额度", format_quota_summary(quota))

    def fetch_selected_snapshot_quota(self) -> None:
        snapshot_id = self.get_selected_snapshot_id()
        if snapshot_id is None:
            messagebox.showwarning("提示", "请先选择一条已保存的数据。")
            return

        try:
            record = find_snapshot_by_id(snapshot_id)
            quota = get_snapshot_quota(record)
            updated = update_local_quota_cache(record.account_id, quota)
        except Exception as error:
            messagebox.showerror("获取额度失败", str(error))
            self.set_status("获取选中额度失败")
            return

        if updated:
            self.refresh_snapshot_list()
            self.tree.selection_set(snapshot_id)
            self.tree.focus(snapshot_id)
            self.on_tree_select(None)
        self.set_status(f"已获取额度: {record.email or record.snapshot_id}")
        messagebox.showinfo("账号额度", format_quota_summary(quota))

    def restore_selected_snapshot(self) -> None:
        snapshot_id = self.get_selected_snapshot_id()
        if snapshot_id is None:
            messagebox.showwarning("提示", "请先选择一条已保存的数据。")
            return

        try:
            restored_record, backup_path = restore_snapshot(snapshot_id)
        except Exception as error:
            messagebox.showerror("还原失败", str(error))
            self.set_status("还原失败")
            return

        backup_hint = f"\n已备份当前 auth.json: {backup_path}" if backup_path else ""
        self.refresh_current_summary()
        self.refresh_snapshot_list()
        self.tree.selection_set(restored_record.snapshot_id)
        self.tree.focus(restored_record.snapshot_id)
        self.on_tree_select(None)
        self.set_status(f"已还原: {restored_record.email or restored_record.snapshot_id}")
        messagebox.showinfo(
            "还原成功",
            "已将所选登录数据还原到 Codex。\n\n"
            + "请重启 VS Code 刷新 Codex 插件。"
            f"{backup_hint}",
        )

    def delete_selected_snapshot(self) -> None:
        snapshot_id = self.get_selected_snapshot_id()
        if snapshot_id is None:
            return

        try:
            deleted_record = delete_snapshot(snapshot_id)
        except Exception as error:
            messagebox.showerror("删除失败", str(error))
            self.set_status("删除失败")
            return

        self.refresh_snapshot_list()
        self.refresh_current_summary()
        self.set_status(f"已删除: {deleted_record.email or deleted_record.snapshot_id}")


def launch_gui() -> int:
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    CodexSwitcherApp(root)
    root.mainloop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex 登录态切换工具，支持 GUI 保存和还原 auth.json 快照。")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("gui", help="启动图形界面")
    subparsers.add_parser("status", help="显示当前 auth.json 登录状态")
    subparsers.add_parser("list", help="列出已保存的登录快照")
    quota_parser = subparsers.add_parser("quota", help="显示当前 Codex 额度")
    quota_parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出原始额度数据")

    subparsers.add_parser("save", help="保存当前登录态")

    restore_parser = subparsers.add_parser("restore", help="按快照ID还原登录态")
    restore_parser.add_argument("snapshot_id", help="快照ID")

    delete_parser = subparsers.add_parser("delete", help="按快照ID删除已保存的登录态")
    delete_parser.add_argument("snapshot_id", help="快照ID")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command in {None, "gui"}:
            return launch_gui()

        if args.command == "status":
            print(format_summary(get_current_auth_summary()))
            return 0

        if args.command == "list":
            print_snapshot_list()
            return 0

        if args.command == "quota":
            quota = get_current_quota()
            if args.as_json:
                print(json.dumps(quota, ensure_ascii=False, indent=2))
            else:
                print(format_quota_summary(quota))
            return 0

        if args.command == "save":
            record = capture_current_snapshot()
            print(f"已保存: {record.email or '未知邮箱'} [{record.snapshot_id}]")
            return 0

        if args.command == "restore":
            record, backup_path = restore_snapshot(args.snapshot_id)
            print(f"已还原: {record.email or '未知邮箱'} [{record.snapshot_id}]")
            if backup_path is not None:
                print(f"已备份当前 auth.json: {backup_path}")
            print("请重启 VS Code 刷新 Codex 插件。")
            return 0

        if args.command == "delete":
            record = delete_snapshot(args.snapshot_id)
            print(f"已删除: {record.email or '未知邮箱'} [{record.snapshot_id}]")
            return 0

        parser.print_help()
        return 0
    except Exception as error:
        print(f"错误: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

# D:\mxcode\python\py38\Scripts\pyinstaller.exe -F -w -n Codex切换器 D:\mxcode\python\chatgpt\codex插件用户切换\main.py