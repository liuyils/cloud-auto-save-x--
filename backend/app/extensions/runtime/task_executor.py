from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session
from treelib import Tree

from app.core.errors import bad_request
from app.db.session import SessionLocal
from app.extensions.runtime.account_manager import DatabaseAccountManager
from app.extensions.runtime.drama_executor import DramaTaskExecutor, SkipTask
from app.extensions.runtime.execution_log import ExecutionLog
from app.extensions.runtime.plugin_hooks import PluginHookRunner, plugin_key_from_definition
from app.extensions.runtime.plugin_loader import sync_plugin_definitions
from app.extensions.runtime.plugin_registry import PluginRegistry
from app.models.drive_account import DriveAccount
from app.models.task import Task
from app.models.task_execution import TaskExecution
from app.models.task_savepath_snapshot import TaskSavepathSnapshot
from app.services.drama_share_autoupdate import is_115_auto_update_task, resolve_drama_shareurl_update
from app.services.drive_account_lsdir_scan import trigger_drive_account_lsdir_targeted_scan
from app.services.system_settings import get_save_rule_runtime_config


logger = logging.getLogger(__name__)


def _plugin_meta_value(payload: Any, key: str, default=None):
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _truncate(s: str, max_len: int) -> str:
    s = str(s or "")
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    return f"{s[:max_len]}...(truncated,len={len(s)})"


def _safe_json_list(payload: str | None) -> list[Any]:
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _normalize_transferred_history(entries: list[Any] | None) -> list[dict[str, str | None]]:
    result: list[dict[str, str | None]] = []
    for raw in entries or []:
        if not isinstance(raw, dict):
            continue
        origin_name = str(raw.get("origin_name") or "").strip()
        target_name = str(raw.get("target_name") or "").strip()
        saved_fid = str(raw.get("saved_fid") or "").strip() or None
        saved_at = str(raw.get("saved_at") or "").strip() or None
        if not origin_name and not target_name:
            continue
        result.append(
            {
                "origin_name": origin_name or None,
                "target_name": target_name or None,
                "saved_fid": saved_fid,
                "saved_at": saved_at,
            }
        )
    return result


def _merge_transferred_history(
    existing: list[dict[str, str | None]] | None,
    new_entries: list[dict[str, str | None]] | None,
) -> list[dict[str, str | None]]:
    merged: list[dict[str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for raw in (existing or []) + (new_entries or []):
        item = _normalize_transferred_history([raw])
        if not item:
            continue
        current = item[0]
        origin_name = str(current.get("origin_name") or "").strip()
        target_name = str(current.get("target_name") or "").strip()
        key = (origin_name, target_name)
        if key in seen:
            continue
        seen.add(key)
        merged.append(current)
    return merged


@dataclass(slots=True)
class ExecutionPayload:
    status: str
    message: str | None
    tree_summary: str | None
    stage: str | None
    run_log: str | None
    adapter_snapshot: dict[str, Any]
    plugins_snapshot: list[dict[str, Any]]


class TaskExecutor:
    def __init__(self, db: Session | None):
        self.db = db

    @staticmethod
    def _read_with_session(loader):
        with SessionLocal() as db:
            return loader(db)

    @staticmethod
    def _write_with_session(writer):
        with SessionLocal() as db:
            result = writer(db)
            db.commit()
            return result

    @staticmethod
    def _persist_execution_detached(execution: TaskExecution) -> TaskExecution:
        def _persist(db: Session) -> None:
            db.add(execution)
            db.flush()
            db.expunge(execution)

        with SessionLocal() as db:
            _persist(db)
            db.commit()
        return execution

    def _trigger_targeted_lsdir_refresh(self, *, task: Task, task_data: dict[str, Any], adapter: Any, tree: Tree, log: ExecutionLog) -> None:
        if str(task_data.get("task_type") or "") != "drama":
            return
        savepath = str(task_data.get("savepath") or "").strip()
        if not savepath:
            log.line("ls_dir 缓存增量刷新: 跳过（缺少 savepath）")
            return
        account_name = str(getattr(adapter, "account_name", "") or task_data.get("account_name") or "").strip()
        if not account_name:
            log.line("ls_dir 缓存增量刷新: 跳过（缺少 account_name）")
            return
        account_id = self._read_with_session(
            lambda db: db.execute(select(DriveAccount.id).where(DriveAccount.name == account_name)).scalars().first()
        )
        if account_id is None:
            log.line("ls_dir 缓存增量刷新: 跳过（无法解析账号）")
            return
        changed_relative_dirs = getattr(tree, "_changed_relative_dirs", None)
        relative_dir_paths = changed_relative_dirs if isinstance(changed_relative_dirs, list) else []
        source = f"task_executor.drama.task_id={int(getattr(task, 'id', 0) or 0)}"
        queued = trigger_drive_account_lsdir_targeted_scan(
            int(account_id),
            savepath=savepath,
            relative_dir_paths=[str(item or "") for item in relative_dir_paths],
            source=source,
        )
        if queued:
            log.line(
                "ls_dir 缓存增量刷新: 已触发"
                f" account_id={int(account_id)} savepath={savepath} touched_dirs={len(relative_dir_paths)}"
            )
        else:
            log.line("ls_dir 缓存增量刷新: 跳过（账号已有扫描任务运行中）")

    @staticmethod
    def _task_to_dict(task: Task) -> dict[str, Any]:
        return {
            'task_uid': task.task_uid,
            'task_type': task.task_type,
            'taskname': task.taskname,
            'shareurl': task.shareurl,
            'savepath': task.savepath,
            'pattern': task.pattern or '',
            'replace': task.replace or '',
            'enddate': task.enddate,
            'ignore_extension': task.ignore_extension,
            'sort_index': task.sort_index,
            'startfid': task.startfid,
            'account_name': task.account_name,
            'update_subdir': task.update_subdir,
            'tmdb_id': task.tmdb_id,
            'tmdb_media_type': task.tmdb_media_type,
            'enabled': task.enabled,
            'addition': json.loads(task.addition_json) if task.addition_json else {},
            'extra': json.loads(task.extra_json) if task.extra_json else {},
            'transferred_history': _safe_json_list(getattr(task, "transferred_history_json", None)),
        }

    def _persist_transferred_history(self, *, task: Task, tree: Tree) -> None:
        task_id = int(getattr(task, "id", 0) or 0)
        if task_id <= 0:
            return
        new_entries = getattr(tree, "_transferred_history_entries", None)
        if not isinstance(new_entries, list) or not new_entries:
            return
        def _persist(db: Session) -> None:
            row = db.get(Task, task_id)
            if row is None:
                return
            existing = _normalize_transferred_history(_safe_json_list(getattr(row, "transferred_history_json", None)))
            merged = _merge_transferred_history(existing, _normalize_transferred_history(new_entries))
            row.transferred_history_json = json.dumps(merged, ensure_ascii=False)

        self._write_with_session(_persist)

    def _capture_snapshot_outside_main_session(
        self,
        *,
        task: Task,
        task_data: dict[str, Any],
        adapter: Any,
        log: ExecutionLog,
    ) -> int | None:
        from app.services.task_savepath_snapshot import capture_and_upsert_snapshot

        account_name = str(getattr(adapter, "account_name", "") or getattr(task, "account_name", "") or "").strip()
        with SessionLocal() as snapshot_db:
            snapshot_row = capture_and_upsert_snapshot(
                snapshot_db,
                task_uid=str(getattr(task, "task_uid", "") or "").strip(),
                savepath=task_data.get("savepath"),
                adapter=adapter,
                account_name=account_name,
                emit_line=log.line,
            )
            snapshot_db.commit()
            if snapshot_row is None:
                return None
            snapshot_db.refresh(snapshot_row)
            return int(getattr(snapshot_row, "id", 0) or 0) or None

    def _attach_snapshot_execution(self, *, snapshot_id: int | None, execution_id: int) -> None:
        if not snapshot_id or execution_id <= 0:
            return
        with SessionLocal() as link_db:
            row = link_db.get(TaskSavepathSnapshot, int(snapshot_id))
            if row is None:
                return
            row.task_execution_id = int(execution_id)
            link_db.commit()

    def _execute_with_adapter(self, adapter: Any, task_data: dict[str, Any]) -> Tree:
        pwd_id, passcode, pdir_fid, _ = adapter.extract_url(task_data['shareurl'])
        token_response = adapter.get_stoken(pwd_id, passcode)
        if token_response.get('status') != 200:
            raise RuntimeError(token_response.get('message') or '获取分享 token 失败')
        stoken = token_response['data']['stoken']
        detail = adapter.get_detail(pwd_id, stoken, pdir_fid or '')
        items = (((detail or {}).get('data') or {}).get('list')) or []

        tree = Tree()
        tree.create_node(task_data['taskname'], 'root')
        if not items:
            tree.create_node('无可处理文件', 'empty', parent='root')
            return tree

        for index, item in enumerate(items[:200], start=1):
            node_id = f'node-{index}'
            name = item.get('file_name') or item.get('name') or item.get('fid') or f'item-{index}'
            tree.create_node(str(name), node_id, parent='root')
        return tree

    def _execute_drama_task(self, adapter: Any, task_data: dict[str, Any], log: ExecutionLog | None) -> Tree:
        executor = DramaTaskExecutor(adapter=adapter, task_data=task_data, log=log)
        tree = executor.execute()
        try:
            setattr(tree, "_transfer_count", int(getattr(executor, "transfer_count", 0) or 0))
        except Exception:
            pass
        return tree

    def run_task(
        self,
        task: Task,
        *,
        log: ExecutionLog | None = None,
        persist_execution: bool = True,
        account_manager: DatabaseAccountManager | None = None,
        init_account_for_task: bool = True,
        defer_plugins: bool = False,
        keep_runtime_tree: bool = False,
    ) -> TaskExecution:
        if not task.enabled:
            raise bad_request('TASK_DISABLED', '任务已禁用')

        log = log or ExecutionLog()
        log.set_stage("start")
        log.section("程序开始")
        log.line(f"执行时间: {log.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
        log.line(f"任务名称: {task.taskname}")
        log.line(f"分享链接: {task.shareurl}")
        log.line(f"保存路径: {task.savepath}")
        log.line("")

        if not defer_plugins:
            try:
                self._write_with_session(lambda pdb: sync_plugin_definitions(pdb))
            except Exception:
                pass
        external_manager = account_manager is not None
        if account_manager is None:
            account_manager = self._read_with_session(lambda db: DatabaseAccountManager(db))
        task_data = self._task_to_dict(task)
        try:
            from app.services.magic_regex import get_enabled_magic_regex_map

            task_data["magic_regex"] = self._read_with_session(lambda db: get_enabled_magic_regex_map(db))
        except Exception:
            task_data["magic_regex"] = {}

        try:
            from app.services.tmdb_settings import get_or_create_tmdb_setting, get_tmdb_runtime_config

            cfg = self._read_with_session(lambda db: get_tmdb_runtime_config(get_or_create_tmdb_setting(db)))
            task_data["disable_guessit_tmdb_fallback_rename"] = bool(cfg.get("disable_guessit_tmdb_fallback_rename") or False)
            task_data["guessit_tmdb_tv_rename_template"] = str(cfg.get("guessit_tmdb_tv_rename_template") or "").strip()
            task_data["guessit_tmdb_movie_rename_template"] = str(cfg.get("guessit_tmdb_movie_rename_template") or "").strip()
        except Exception:
            task_data["disable_guessit_tmdb_fallback_rename"] = False
            task_data["guessit_tmdb_tv_rename_template"] = ""
            task_data["guessit_tmdb_movie_rename_template"] = ""

        try:
            save_rule_config = self._read_with_session(lambda db: get_save_rule_runtime_config(db))
            task_data["skip_transferred_history_enabled"] = bool(save_rule_config.get("enable_skip_transferred_history") or False)
        except Exception:
            task_data["skip_transferred_history_enabled"] = False
        task_data["transferred_history"] = _normalize_transferred_history(task_data.get("transferred_history"))

        if str(getattr(task, "task_type", "") or "") == "drama":
            extra = task_data.get("extra") or {}
            runweek_mode = str(extra.get("runweek_mode") or "manual").strip().lower()
            tmdb_id = int(task_data.get("tmdb_id") or 0)
            tmdb_media_type = str(task_data.get("tmdb_media_type") or "").strip().lower()
            task_data["tmdb_configured"] = False
            task_data["tmdb_update_weekdays"] = []
            task_data["tmdb_episode_weekdays"] = []
            if runweek_mode == "auto" and tmdb_id > 0 and tmdb_media_type == "tv":
                try:
                    from app.services.tmdb_cache import get_tmdb_detail_cached

                    configured, _detail, update_weekdays, episode_weekdays, _row = self._read_with_session(
                        lambda db: get_tmdb_detail_cached(db, media_type="tv", tmdb_id=tmdb_id)
                    )
                    task_data["tmdb_configured"] = bool(configured)
                    task_data["tmdb_update_weekdays"] = update_weekdays or []
                    task_data["tmdb_episode_weekdays"] = episode_weekdays or []
                except Exception:
                    task_data["tmdb_configured"] = False
                    task_data["tmdb_update_weekdays"] = []
                    task_data["tmdb_episode_weekdays"] = []

        if not bool(task_data.get("disable_guessit_tmdb_fallback_rename")):
            tmdb_id = int(task_data.get("tmdb_id") or 0)
            tmdb_media_type = str(task_data.get("tmdb_media_type") or "").strip().lower()
            if tmdb_id > 0 and tmdb_media_type in {"movie", "tv"}:
                try:
                    from app.services.tmdb_cache import get_tmdb_detail_cached

                    configured, detail, _weekdays, _episode_weekdays, _row = self._read_with_session(
                        lambda db: get_tmdb_detail_cached(db, media_type=tmdb_media_type, tmdb_id=tmdb_id)
                    )
                    if configured and isinstance(detail, dict):
                        task_data["tmdb_series_title"] = detail.get("name") if tmdb_media_type == "tv" else detail.get("title")
                        if tmdb_media_type == "tv":
                            raw_seasons = detail.get("seasons")
                            task_data["tmdb_tv_seasons"] = raw_seasons if isinstance(raw_seasons, list) else None
                        if tmdb_media_type == "movie":
                            rd = str(detail.get("release_date") or "").strip()
                            if len(rd) >= 4 and rd[:4].isdigit():
                                task_data["tmdb_year"] = int(rd[:4])
                    else:
                        task_data["tmdb_series_title"] = None
                except Exception:
                    task_data["tmdb_series_title"] = None
            else:
                task_data["tmdb_series_title"] = None
        if init_account_for_task:
            account_manager.init_for_tasks([task_data])
        default_adapter = account_manager.get_default_adapter()
        plugins = []
        should_defer_plugins = bool(defer_plugins) or str(task_data.get("task_type") or "") == "drama"
        if not should_defer_plugins:
            log.set_stage("load_plugins")
            plugins = self._write_with_session(lambda db: PluginRegistry(db).load_active_plugins())
            if plugins:
                # log.line("启用插件: " + ", ".join([p["definition"].plugin_key for p in plugins]))
                for item in plugins:
                    definition = item.get("definition")
                    config = item.get("config")
                    instance = item.get("instance")
                    key = plugin_key_from_definition(definition)
                    rs = _plugin_meta_value(config, "runtime_status", None)
                    err = _plugin_meta_value(config, "last_error", None)
                    active = bool(getattr(instance, "is_active", False))
                    meta = []
                    if rs:
                        meta.append(f"status={rs}")
                    meta.append(f"is_active={'Y' if active else 'N'}")
                    if err:
                        meta.append(f"error={str(err)}")
                    # log.line(f"- {key} " + " ".join(meta))
            else:
                log.line("启用插件: (无)")
            log.set_stage("plugin_task_before")
            # log.section("插件前置")
            task_list = PluginHookRunner.task_before(plugins, [task_data], default_adapter, emit_line=log.line)
            task_data = task_list[0] if task_list else task_data
        adapter = account_manager.get_adapter_for_task(task_data)
        if adapter is None and external_manager:
            try:
                fallback_manager = self._read_with_session(lambda db: DatabaseAccountManager(db))
                fallback_manager.init_for_tasks([task_data])
                account_manager = fallback_manager
                adapter = account_manager.get_adapter_for_task(task_data)
            except Exception:
                adapter = None
        started_at = datetime.now()
        task_id = int(getattr(task, "id", 0) or 0)
        snapshot_row_id: int | None = None

        if adapter is None:
            log.set_stage("select_account")
            log.section("验证账户")
            log.line("FAIL: 没有可用的驱动账号")
            log.set_stage("end")
            execution = TaskExecution(
                task_id=task_id,
                status='failed',
                started_at=started_at,
                finished_at=datetime.now(),
                message='没有可用的驱动账号',
                stage=log.stage,
                run_log=log.render(),
                adapter_snapshot=json.dumps({}, ensure_ascii=False),
                plugins_snapshot=json.dumps([], ensure_ascii=False),
            )
            if not persist_execution:
                execution.id = 0
                return execution
            self._persist_execution_detached(execution)
            return execution

        try:
            if getattr(task, "shareurl_ban", None):
                log.set_stage("shareurl_ban")
                log.section("任务封禁")
                log.line(f"跳过: {str(getattr(task, 'shareurl_ban', '') or '').strip()}")
                raise SkipTask(f"分享链接异常已封禁：{str(getattr(task, 'shareurl_ban', '') or '').strip()}")
            log.set_stage("validate_account")
            log.section("验证账户")
            if not getattr(adapter, 'is_active', False):
                adapter.init()
            log.line(f"OK: 账户 '{getattr(adapter, 'nickname', '')}' ({getattr(adapter, 'DRIVE_TYPE', '')}) 已就绪")
            if task_data.get('task_type') == 'drama':
                log.set_stage("execute_drama")
                log.section("转存任务")
                tree = self._execute_drama_task(adapter, task_data, log)
                self._persist_transferred_history(task=task, tree=tree)
            else:
                log.set_stage("execute_generic")
                log.section("转存任务")
                tree = self._execute_with_adapter(adapter, task_data)
            has_new_files = False
            if str(task_data.get("task_type") or "") == "drama":
                transfer_count = None
                if hasattr(tree, "_transfer_count"):
                    try:
                        transfer_count = int(getattr(tree, "_transfer_count") or 0)
                    except Exception:
                        transfer_count = 0
                if transfer_count is None:
                    try:
                        transfer_count = int(getattr(tree, "size", lambda: 0)() > 1)
                    except Exception:
                        transfer_count = 0
                has_new_files = bool(transfer_count)
            if keep_runtime_tree:
                setattr(task, "_runtime_tree", tree)
            setattr(task, "_runtime_task_data", task_data)
            setattr(task, "_runtime_adapter", adapter)
            setattr(task, "_runtime_has_new_files", has_new_files)
            if not defer_plugins:
                if str(task_data.get("task_type") or "") == "drama":
                    if not has_new_files:
                        log.set_stage("plugin_run")
                        log.section("插件执行")
                        log.line("跳过: 本次无新增文件")
                    else:
                        log.set_stage("load_plugins")
                        plugins = self._write_with_session(lambda db: PluginRegistry(db).load_active_plugins())
                        log.set_stage("plugin_run")
                        log.section("插件执行")
                        if not plugins:
                            log.line("无可执行插件")
                        else:
                            for item in plugins:
                                definition = item.get("definition")
                                instance = item.get("instance")
                                key = plugin_key_from_definition(definition)
                                if not bool(getattr(instance, "is_active", False)):
                                    log.line(f"SKIP: {key}（is_active=false）")
                                    continue
                                if not hasattr(instance, "run"):
                                    log.line(f"SKIP: {key}（缺少 run）")
                                    continue
                                log.line(f"RUN: {key}")
                        task_data = PluginHookRunner.run(plugins, task_data, adapter, tree, emit_line=log.line)
                        log.set_stage("plugin_task_after")
                        log.section("插件收尾")
                        log.line("说明: task_after 为可选钩子，缺少 task_after 不影响插件在“插件执行(run)”阶段运行。")
                        if plugins:
                            for item in plugins:
                                definition = item.get("definition")
                                instance = item.get("instance")
                                key = plugin_key_from_definition(definition)
                                if not bool(getattr(instance, "is_active", False)):
                                    log.line(f"SKIP: {key}（is_active=false）")
                                    continue
                                if not hasattr(instance, "task_after"):
                                    log.line(f"INFO: {key}（无 task_after）")
                                    continue
                                log.line(f"RUN: {key}（task_after）")
                        PluginHookRunner.task_after(plugins, [task_data], default_adapter or adapter, emit_line=log.line)
                else:
                    log.set_stage("plugin_run")
                    log.section("插件执行")
                    if not plugins:
                        log.line("无可执行插件")
                    else:
                        for item in plugins:
                            definition = item.get("definition")
                            instance = item.get("instance")
                            key = plugin_key_from_definition(definition)
                            if not bool(getattr(instance, "is_active", False)):
                                # log.line(f"SKIP: {key}（is_active=false）")
                                continue
                            if not hasattr(instance, "run"):
                                log.line(f"SKIP: {key}（缺少 run）")
                                continue
                            log.line(f"RUN: {key}")
                    task_data = PluginHookRunner.run(plugins, task_data, adapter, tree, emit_line=log.line)
                    log.set_stage("plugin_task_after")
                    log.section("插件收尾")
                    log.line("说明: task_after 为可选钩子，缺少 task_after 不影响插件在“插件执行(run)”阶段运行。")
                    if plugins:
                        for item in plugins:
                            definition = item.get("definition")
                            instance = item.get("instance")
                            key = plugin_key_from_definition(definition)
                            if not bool(getattr(instance, "is_active", False)):
                                # log.line(f"SKIP: {key}（task_after, is_active=false）")
                                continue
                            if not hasattr(instance, "task_after"):
                                log.line(f"INFO: {key}（无 task_after）")
                                continue
                            log.line(f"RUN: {key}（task_after）")
                    PluginHookRunner.task_after(plugins, [task_data], default_adapter or adapter, emit_line=log.line)
            if str(task_data.get("task_type") or "") == "drama" and self._read_with_session(
                lambda db: is_115_auto_update_task(db, db.get(Task, task_id), respect_toggle=True) if db.get(Task, task_id) is not None else False
            ):
                log.set_stage("shareurl_autoupdate_after")
                log.section("自动换链")
                try:
                    update_result = self._write_with_session(
                        lambda db: resolve_drama_shareurl_update(db, db.get(Task, task_id), respect_toggle=True)
                        if db.get(Task, task_id) is not None
                        else {"updated": False, "checked": False, "reason": "任务不存在"}
                    )
                    if bool(update_result.get("updated")):
                        season = update_result.get("season")
                        episode = update_result.get("episode")
                        se = ""
                        if season is not None and episode is not None:
                            se = f" S{int(season):02d}E{int(episode):02d}"
                        log.line(
                            "OK: 自动换链成功"
                            f"{se} old={str(update_result.get('old_shareurl') or '').strip()}"
                            f" new={str(update_result.get('new_shareurl') or '').strip()}"
                        )
                    elif bool(update_result.get("checked")):
                        reason = str(update_result.get("reason") or "未找到更高集数链接")
                        detail = update_result.get("reason_detail")
                        if isinstance(detail, dict) and detail:
                            log.line(f"跳过: {reason}")
                        else:
                            log.line(f"跳过: {reason}")
                    else:
                        log.line(f"跳过: {str(update_result.get('reason') or '当前任务不满足自动换链条件')}")
                except Exception as exc:
                    logger.warning(
                        "任务执行后自动换链失败 task_id=%s task_uid=%s err=%s",
                        task_id,
                        str(getattr(task, "task_uid", "") or ""),
                        str(exc),
                    )
                    log.line(f"WARN: 自动换链失败 err={str(exc).strip() or type(exc).__name__}")
            if persist_execution and task_id > 0:
                try:
                    snapshot_row_id = self._capture_snapshot_outside_main_session(
                        task=task,
                        task_data=task_data,
                        adapter=adapter,
                        log=log,
                    )
                except Exception:
                    snapshot_row_id = None
            if has_new_files:
                try:
                    self._trigger_targeted_lsdir_refresh(task=task, task_data=task_data, adapter=adapter, tree=tree, log=log)
                except Exception as exc:
                    logger.warning(
                        "任务执行后触发 ls_dir 缓存增量刷新失败 task_id=%s task_uid=%s err=%s",
                        task_id,
                        str(getattr(task, "task_uid", "") or ""),
                        str(exc),
                    )
                    log.line(f"WARN: ls_dir 缓存增量刷新触发失败 err={str(exc).strip() or type(exc).__name__}")
            log.set_stage("end")
            log.section("程序结束")
            finished_at_local = datetime.now()
            duration_s = (finished_at_local - log.started_at).total_seconds()
            log.line(f"状态: success")
            log.line(f"运行时长: {duration_s:.2f}s")
            allow_once = bool((task_data.get("extra") or {}).get("allow_once"))
            if (
                persist_execution
                and task_id > 0
                and str(task_data.get("task_type") or "") == "drama"
                and allow_once
                and bool(getattr(task, "enabled", False))
            ):
                self._write_with_session(
                    lambda db: setattr(db.get(Task, task_id), "enabled", False) if db.get(Task, task_id) is not None else None
                )
                log.line("运行一次: 本次执行成功，已自动禁用任务")
            payload = ExecutionPayload(
                status='success',
                message='执行完成',
                tree_summary=str(tree),
                stage=log.stage,
                run_log=log.render(),
                adapter_snapshot={
                    'name': getattr(adapter, 'nickname', ''),
                    'drive_type': getattr(adapter, 'DRIVE_TYPE', ''),
                    'active': bool(getattr(adapter, 'is_active', False)),
                },
                plugins_snapshot=[
                    {
                        'plugin_key': plugin_key_from_definition(item.get('definition')),
                        'enabled': bool(_plugin_meta_value(item.get('config'), 'enabled', False)),
                        'runtime_status': _plugin_meta_value(item.get('config'), 'runtime_status', None),
                    }
                    for item in plugins
                ],
            )
        except Exception as exc:
            status = 'skipped' if isinstance(exc, SkipTask) else 'failed'
            stage = log.stage or "unknown"
            message = str(exc).strip() or type(exc).__name__
            try:
                logger.exception(
                    "任务执行异常 task_id=%s task_uid=%s task_type=%s stage=%s err=%s",
                    task_id,
                    str(getattr(task, "task_uid", "") or ""),
                    str(getattr(task, "task_type", "") or ""),
                    stage,
                    message,
                )
            except Exception:
                pass
            if (
                status == "failed"
                and str(getattr(task, "task_type", "") or "") == "drama"
                and stage in {"share_parse", "get_stoken", "fetch_share_items"}
                and not str(getattr(task, "shareurl_ban", "") or "").strip()
            ):
                if persist_execution and task_id > 0:
                    self._write_with_session(
                        lambda db: setattr(db.get(Task, task_id), "shareurl_ban", f"阶段={stage}：{message}")
                        if db.get(Task, task_id) is not None
                        else None
                    )
            log.section("异常")
            log.line(f"阶段={stage}: {message}")

            log.set_stage(stage)
            log.section("程序结束")
            finished_at_local = datetime.now()
            duration_s = (finished_at_local - log.started_at).total_seconds()
            log.line(f"状态: {status}")
            log.line(f"运行时长: {duration_s:.2f}s")
            payload = ExecutionPayload(
                status=status,
                message=f"阶段={stage}：{message}",
                tree_summary=None,
                stage=stage,
                run_log=log.render(),
                adapter_snapshot={
                    'name': getattr(adapter, 'nickname', ''),
                    'drive_type': getattr(adapter, 'DRIVE_TYPE', ''),
                    'active': bool(getattr(adapter, 'is_active', False)),
                },
                plugins_snapshot=[
                    {
                        'plugin_key': plugin_key_from_definition(item.get('definition')),
                        'enabled': bool(_plugin_meta_value(item.get('config'), 'enabled', False)),
                        'runtime_status': _plugin_meta_value(item.get('config'), 'runtime_status', None),
                    }
                    for item in plugins
                ],
            )

        execution = TaskExecution(
            task_id=task_id,
            status=payload.status,
            started_at=started_at,
            finished_at=datetime.now(),
            tree_summary=payload.tree_summary,
            message=payload.message,
            stage=payload.stage,
            run_log=payload.run_log,
            adapter_snapshot=json.dumps(payload.adapter_snapshot, ensure_ascii=False),
            plugins_snapshot=json.dumps(payload.plugins_snapshot, ensure_ascii=False),
        )
        if not persist_execution:
            execution.id = 0
            setattr(execution, "_has_new_files", bool(getattr(task, "_runtime_has_new_files", False)))
            if keep_runtime_tree:
                setattr(execution, "_runtime_tree", getattr(task, "_runtime_tree", None))
            setattr(execution, "_runtime_task_data", getattr(task, "_runtime_task_data", None))
            setattr(execution, "_runtime_adapter", getattr(task, "_runtime_adapter", None))
            return execution
        self._persist_execution_detached(execution)
        setattr(execution, "_snapshot_row_id", snapshot_row_id)
        setattr(execution, "_has_new_files", bool(getattr(task, "_runtime_has_new_files", False)))
        if keep_runtime_tree:
            setattr(execution, "_runtime_tree", getattr(task, "_runtime_tree", None))
        setattr(execution, "_runtime_task_data", getattr(task, "_runtime_task_data", None))
        setattr(execution, "_runtime_adapter", getattr(task, "_runtime_adapter", None))
        return execution
