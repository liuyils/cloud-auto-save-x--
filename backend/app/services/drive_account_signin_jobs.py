from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
import uuid
from typing import Any

from app.core.errors import ApiError, not_found
from app.db.session import SessionLocal
from app.services.drive_accounts import sign_in_drive_account

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="drive-signin")
_jobs_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_JOB_RETENTION = timedelta(hours=6)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _cleanup_expired_jobs(now: datetime | None = None) -> None:
    current = now or _utcnow()
    expired_ids: list[str] = []
    for job_id, job in _jobs.items():
        finished_at = job.get("finished_at")
        if isinstance(finished_at, datetime) and current - finished_at > _JOB_RETENTION:
            expired_ids.append(job_id)
    for job_id in expired_ids:
        _jobs.pop(job_id, None)


def _serialize_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": str(job.get("job_id") or ""),
        "account_id": int(job.get("account_id") or 0),
        "status": str(job.get("status") or "pending"),
        "message": str(job.get("message") or ""),
        "result": job.get("result"),
        "error": job.get("error"),
        "created_at": _serialize_dt(job.get("created_at")),
        "started_at": _serialize_dt(job.get("started_at")),
        "finished_at": _serialize_dt(job.get("finished_at")),
    }


def submit_drive_account_signin_job(account_id: int) -> dict[str, Any]:
    now = _utcnow()
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "account_id": int(account_id),
        "status": "pending",
        "message": "签到任务已提交",
        "result": None,
        "error": None,
        "created_at": now,
        "started_at": None,
        "finished_at": None,
    }
    with _jobs_lock:
        _cleanup_expired_jobs(now)
        _jobs[job_id] = job
    _executor.submit(_run_drive_account_signin_job, job_id, int(account_id))
    return _serialize_job(job)


def get_drive_account_signin_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        _cleanup_expired_jobs()
        job = _jobs.get(str(job_id))
        if job is None:
            raise not_found("DRIVE_ACCOUNT_SIGNIN_JOB_NOT_FOUND", "签到任务不存在或已过期")
        return _serialize_job(job)


def _run_drive_account_signin_job(job_id: str, account_id: int) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["status"] = "running"
        job["message"] = "签到任务执行中"
        job["started_at"] = _utcnow()

    with SessionLocal() as db:
        try:
            result = sign_in_drive_account(db, int(account_id))
            db.commit()
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is None:
                    return
                job["status"] = "succeeded"
                job["message"] = str((result or {}).get("message") or "签到成功")
                job["result"] = result
                job["finished_at"] = _utcnow()
        except ApiError as exc:
            db.rollback()
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is None:
                    return
                job["status"] = "failed"
                job["message"] = exc.message
                job["error"] = {"code": exc.code, "message": exc.message, "detail": exc.detail}
                job["finished_at"] = _utcnow()
        except Exception as exc:
            db.rollback()
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is None:
                    return
                job["status"] = "failed"
                job["message"] = str(exc)
                job["error"] = {"message": str(exc)}
                job["finished_at"] = _utcnow()
