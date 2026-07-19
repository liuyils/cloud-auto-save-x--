import hashlib
import json
import logging
import posixpath
import random
import re
import time
from typing import Any
from urllib.parse import quote, unquote, urlencode, urljoin

import requests


logger = logging.getLogger(__name__)


class Fnv_refresh_v2:
    plugin_name = "fnv_refresh_v2"
    plugin_version = "py-compat"
    API_PREFIX = "/v/api/v1"
    DEFAULT_HEADERS = {
        "X-Trim-Client": "web",
        "X-Trim-Client-Version": "610",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    NO_SIGN_PATHS = {
        f"{API_PREFIX}/task/running",
        f"{API_PREFIX}/play/record",
        f"{API_PREFIX}/subtitle/upload",
    }
    NO_SIGN_PREFIXES = (
        f"{API_PREFIX}/sys/img/",
        f"{API_PREFIX}/img/",
        f"{API_PREFIX}/concat/",
        f"{API_PREFIX}/media/",
    )

    default_config = {
        "tips": "填写 endpoint、mount_quark、secret、fnv_token 后即可启用；token/long_token 可选。",
        "endpoint": "",
        "username": "",
        "password": "",
        "mount_quark": "",
        "remove_useless_wait": 180,
        "token": "",
        "long_token": "",
        "secret": "",
        "fnv_token": "",
    }

    default_task_config: dict[str, Any] = {}

    def __init__(self, **kwargs):
        self.plugin_name = self.__class__.plugin_name
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)
        self.is_active = False
        self.api_key = ""
        self.app_name = "trimemedia-web"
        self._discovery_attempted = False
        self._login_attempted = False

        for key, value in self.default_config.items():
            setattr(self, key, kwargs.get(key, value))

        self.endpoint = self._normalize_endpoint(self.endpoint)
        self.mount_quark = self._normalize_path(self.mount_quark)
        self.remove_useless_wait = self._as_int(self.remove_useless_wait, default=180)

        if not self.endpoint or not self.mount_quark:
            logger.warning("%s: 缺少 endpoint 或 mount_quark，插件未激活", self.plugin_name)
            return

        self.is_active = self._bootstrap_runtime_auth(force=False)
        if self.is_active:
            logger.info("%s: 插件已激活", self.plugin_name)
        else:
            logger.warning(
                "%s: 插件未激活，需提供可用的 fnv_token 或 username/password",
                self.plugin_name,
            )

    def run(self, task, **_kwargs):
        if not self.is_active:
            return task

        target_path = self._build_target_path(task.get("savepath"))
        if not target_path:
            return task

        library_id = self._get_library_id(target_path)
        if not library_id:
            logger.warning("%s: 未找到与路径匹配的媒体库 %s", self.plugin_name, target_path)
            return task

        if self._scan_library(library_id, target_path):
            logger.info("%s: 已触发飞牛影视刷新 %s", self.plugin_name, target_path)
            if self.remove_useless_wait >= 0:
                self._remove_useless()
        return task

    def _bootstrap_runtime_auth(self, *, force: bool) -> bool:
        if not self.endpoint:
            return False

        if force or ((not self.secret or not self.api_key) and not self._discovery_attempted):
            self._discovery_attempted = True
            self._extract_signing_keys()

        if self.username and self.password and (force or not self.fnv_token):
            if force or not self._login_attempted:
                self._login_attempted = True
                self._login()

        return bool(self.fnv_token)

    def _extract_signing_keys(self) -> None:
        if self.secret and self.api_key:
            return
        try:
            js_files = self._discover_js_files()
        except Exception as exc:
            logger.warning("%s: 获取前端入口 JS 失败 %s", self.plugin_name, exc)
            return

        for js_url in js_files:
            try:
                js_text = self._fetch_text(js_url)
            except Exception as exc:
                logger.debug("%s: 读取入口 JS 失败 %s %s", self.plugin_name, js_url, exc)
                continue
            if not self.secret:
                self.secret = self._extract_secret(js_text) or self.secret
            if not self.api_key:
                self.api_key = self._extract_api_key(js_text) or self.api_key
            if self.secret and self.api_key:
                return

        for js_url in js_files:
            try:
                js_text = self._fetch_text(js_url)
                chunk_urls = self._extract_imported_chunks(js_url, js_text)
            except Exception as exc:
                logger.debug("%s: 读取 chunk 索引失败 %s %s", self.plugin_name, js_url, exc)
                continue
            for chunk_url in chunk_urls:
                try:
                    chunk_text = self._fetch_text(chunk_url)
                except Exception as exc:
                    logger.debug("%s: 读取 chunk 失败 %s %s", self.plugin_name, chunk_url, exc)
                    continue
                if not self.secret:
                    self.secret = self._extract_secret(chunk_text) or self.secret
                if not self.api_key:
                    self.api_key = self._extract_api_key(chunk_text) or self.api_key
                if self.secret and self.api_key:
                    return

        missing = []
        if not self.secret:
            missing.append("secret")
        if not self.api_key:
            missing.append("api_key")
        if missing:
            logger.warning("%s: 自动提取签名信息失败，缺少 %s", self.plugin_name, "/".join(missing))

    def _discover_js_files(self) -> list[str]:
        html = self._fetch_text(f"{self.endpoint}/v/")
        scripts = re.findall(r'src="([^"]+\.js)"', html)
        return [urljoin(self.endpoint, item) for item in scripts]

    def _fetch_text(self, url: str) -> str:
        response = self.session.get(url, timeout=5)
        response.raise_for_status()
        return response.text

    def _login(self) -> bool:
        if not self.username or not self.password:
            return False

        payload = {
            "username": self.username,
            "password": self._sha256(str(self.password)),
            "app_name": self.app_name or "trimemedia-web",
        }
        url = f"{self.endpoint}/v/api/v2/user/loginByPassword"
        headers = {
            "Content-Type": "application/json",
            **self._cookie_headers(),
        }
        try:
            response = self.session.post(
                url,
                headers=headers,
                data=self._serialize_data(payload).encode("utf-8"),
                timeout=5,
            )
            response.raise_for_status()
            payload_data = response.json()
        except Exception as exc:
            logger.warning("%s: 登录失败 %s", self.plugin_name, exc)
            return False

        if not isinstance(payload_data, dict) or payload_data.get("code") != 0:
            logger.warning(
                "%s: 登录失败 %s",
                self.plugin_name,
                self._payload_message(payload_data),
            )
            return False

        token = self._find_first(payload_data.get("data"), {"token"})
        if not token:
            logger.warning("%s: 登录响应缺少 token", self.plugin_name)
            return False

        self.fnv_token = str(token)
        self.session.cookies.set("Trim-MC-token", self.fnv_token)
        return True

    def _request(
        self,
        method: str,
        rel_url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        quiet: bool = False,
        retry_auth: bool = True,
    ) -> dict[str, Any] | None:
        if not self.fnv_token and self.username and self.password:
            self._bootstrap_runtime_auth(force=False)

        url = f"{self.endpoint.rstrip('/')}{rel_url}"
        headers = self._build_headers(method=method, rel_url=rel_url, params=params, data=data)
        try:
            response = self.session.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                data=self._serialize_data(data if data is not None else {}).encode("utf-8"),
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            if not quiet:
                logger.warning("%s: 请求失败 %s %s", self.plugin_name, rel_url, exc)
            if retry_auth and self.username and self.password and self._bootstrap_runtime_auth(force=True):
                return self._request(
                    method,
                    rel_url,
                    params=params,
                    data=data,
                    quiet=quiet,
                    retry_auth=False,
                )
            return None

        if not isinstance(payload, dict):
            if not quiet:
                logger.warning("%s: 接口返回非字典响应 %s", self.plugin_name, rel_url)
            return None

        if self._is_auth_failure(payload):
            if retry_auth and self.username and self.password and self._bootstrap_runtime_auth(force=True):
                return self._request(
                    method,
                    rel_url,
                    params=params,
                    data=data,
                    quiet=quiet,
                    retry_auth=False,
                )
            if not quiet:
                logger.warning("%s: 接口认证失败 %s %s", self.plugin_name, rel_url, self._payload_message(payload))
            return payload

        if payload.get("code") not in (0, None) and not quiet:
            logger.warning(
                "%s: 接口返回异常 %s %s",
                self.plugin_name,
                rel_url,
                self._payload_message(payload),
            )
        return payload

    def _build_headers(
        self,
        *,
        method: str,
        rel_url: str,
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
    ) -> dict[str, str]:
        headers = {
            **self.DEFAULT_HEADERS,
            **self._cookie_headers(),
        }
        if self.fnv_token:
            headers["Authorization"] = self.fnv_token
        if self._needs_signature(rel_url, method) and self.secret and self.api_key:
            headers["authx"] = self._cse_sign(method, rel_url, params=params, data=data)
        return headers

    def _cookie_headers(self) -> dict[str, str]:
        cookies: list[str] = []
        if self.token:
            cookies.append(f"fnos-token={self.token}")
        if self.long_token:
            cookies.append(f"fnos-long-token={self.long_token}")
        if self.fnv_token:
            cookies.append(f"Trim-MC-token={self.fnv_token}")
        return {"Cookie": "; ".join(cookies)} if cookies else {}

    def _get_library_id(self, target_path: str) -> str | None:
        payload = self._request("GET", f"{self.API_PREFIX}/mdb/list")
        libraries = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(libraries, list) or not libraries:
            return None

        if len(libraries) == 1:
            return self._extract_guid(libraries[0])

        best_guid = None
        best_score = -1
        for item in libraries:
            guid = self._extract_guid(item)
            if not guid:
                continue
            for path_value in self._extract_path_candidates(item):
                if self._path_matches_library(target_path, path_value) and len(path_value) > best_score:
                    best_guid = guid
                    best_score = len(path_value)
        return best_guid

    def _scan_library(self, library_id: str, target_path: str) -> bool:
        payload = self._request(
            "POST",
            f"{self.API_PREFIX}/mdb/scan/{library_id}",
            data={"dir_list": [target_path]},
        )
        return bool(payload and payload.get("code") == 0)

    def _remove_useless(self) -> None:
        wait_time = self.remove_useless_wait
        for body in ({"wait_time": wait_time}, {"wait": wait_time}, {"seconds": wait_time}):
            payload = self._request("POST", f"{self.API_PREFIX}/task/removeUseless", data=body, quiet=True)
            if payload and payload.get("code") == 0:
                logger.info("%s: 已清理缺失媒体等待任务", self.plugin_name)
                return

    def _build_target_path(self, _savepath: str) -> str:
        mount_quark = self._normalize_path(self.mount_quark)
        if not mount_quark:
            return ""
        return mount_quark

    def _extract_guid(self, item: Any) -> str | None:
        candidates = self._find_all(item, {"guid", "id", "mdb_guid"})
        for value in candidates:
            if value:
                return str(value)
        return None

    def _extract_path_candidates(self, item: Any) -> list[str]:
        raw = self._find_all(
            item,
            {
                "dir",
                "dir_list",
                "path",
                "root_dir",
                "root_path",
                "mount_path",
                "library_path",
                "media_path",
                "folder",
            },
        )
        values: list[str] = []
        for value in raw:
            if isinstance(value, str) and value.startswith("/"):
                values.append(self._normalize_path(value))
            elif isinstance(value, list):
                for sub in value:
                    if isinstance(sub, str) and sub.startswith("/"):
                        values.append(self._normalize_path(sub))
        return list(dict.fromkeys(values))

    def _path_matches_library(self, target_path: str, library_path: str) -> bool:
        target = self._normalize_path(target_path)
        library = self._normalize_path(library_path)
        if not target or not library:
            return False
        if target == library:
            return True
        return target.startswith(library.rstrip("/") + "/")

    def _needs_signature(self, path: str, method: str) -> bool:
        if "/play/record" in path and method.upper() == "DELETE":
            return True
        if path in self.NO_SIGN_PATHS:
            return False
        return not any(path.startswith(prefix) for prefix in self.NO_SIGN_PREFIXES)

    def _cse_sign(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> str:
        nonce = str(random.randint(100000, 999999))
        timestamp = str(int(time.time() * 1000))
        body_hash = self._build_body_hash(method, data=data, params=params)
        sign = self._md5("_".join([self.secret, path, nonce, timestamp, body_hash, self.api_key]))
        return f"nonce={nonce}&timestamp={timestamp}&sign={sign}"

    def _build_body_hash(
        self,
        method: str,
        *,
        data: dict[str, Any] | None,
        params: dict[str, Any] | None,
    ) -> str:
        if method.upper() == "GET" and params:
            serialized = urlencode(sorted(params.items()), quote_via=quote)
            try:
                serialized = unquote(serialized)
            except Exception:
                pass
            return self._md5(serialized)
        return self._md5(self._serialize_data(data))

    def _is_auth_failure(self, payload: dict[str, Any]) -> bool:
        code = payload.get("code")
        if code in {-2, 401, 403}:
            return True
        message = self._payload_message(payload).lower()
        return "token" in message and ("invalid" in message or "expired" in message or "失效" in message)

    def _payload_message(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return str(payload)
        message = payload.get("msg") or payload.get("message") or payload.get("code")
        return str(message)

    def _find_first(self, value: Any, keys: set[str]) -> str | None:
        matches = self._find_all(value, keys)
        for item in matches:
            if item:
                return str(item)
        return None

    def _find_all(self, value: Any, keys: set[str]) -> list[Any]:
        hits: list[Any] = []
        if isinstance(value, dict):
            for key, sub in value.items():
                if key in keys:
                    hits.append(sub)
                hits.extend(self._find_all(sub, keys))
        elif isinstance(value, list):
            for item in value:
                hits.extend(self._find_all(item, keys))
        return hits

    def _extract_imported_chunks(self, entry_url: str, js_text: str) -> list[str]:
        imports = re.findall(r'from\s*["\']\./([^"\']+)["\']', js_text)
        base = entry_url.rsplit("/", 1)[0] + "/"
        return [base + item for item in imports if item.endswith(".js")]

    @staticmethod
    def _extract_secret(js_text: str) -> str | None:
        match = re.search(
            r'\[`([A-Za-z0-9+/=]{20,50})`,\s*r,\s*s,\s*c,\s*o,\s*t\]\.join',
            js_text,
        )
        return match.group(1) if match else None

    @staticmethod
    def _extract_api_key(js_text: str) -> str | None:
        match = re.search(
            r'new\s+Uint8Array\(\[([\d,\s]+)\]\).*?t\[n\]=e\[n\]\^(\d+)',
            js_text,
            re.DOTALL,
        )
        if not match:
            return None
        try:
            byte_values = [int(item.strip()) for item in match.group(1).split(",") if item.strip()]
            xor_key = int(match.group(2))
            return bytes(value ^ xor_key for value in byte_values).decode("utf-8")
        except Exception:
            return None

    @staticmethod
    def _normalize_endpoint(endpoint: str) -> str:
        endpoint = str(endpoint or "").strip().rstrip("/")
        if not endpoint:
            return ""
        if "://" not in endpoint:
            endpoint = f"http://{endpoint}"
        return endpoint

    @staticmethod
    def _normalize_path(path: str) -> str:
        path = str(path or "").strip()
        if not path:
            return ""
        path = path.replace("\\", "/")
        if not path.startswith("/"):
            path = "/" + path
        normalized = posixpath.normpath(path)
        return "/" if normalized == "." else normalized

    @staticmethod
    def _as_int(value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _md5(value: str) -> str:
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _serialize_data(data: Any) -> str:
        if isinstance(data, dict):
            return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if isinstance(data, str):
            return data
        if not data:
            return ""
        return ""
