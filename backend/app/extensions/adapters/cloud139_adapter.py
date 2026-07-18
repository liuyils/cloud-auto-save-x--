# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import random
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.serialization import load_der_public_key

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter


logger = logging.getLogger(__name__)


class Cloud139Adapter(BaseCloudDriveAdapter):
    DRIVE_TYPE = "cloud139"
    DRIVE_NAME = "移动云盘"
    CONFIG_FORMAT = "kv"
    default_config = {
        "authorization": "",
        "cookie": "",
        "username": "",
        "password": "",
        "lsdir_cache_path": "",
        "strm_scan_path": "",
        "debug": False,
    }
    config_fields = [
        {
            "key": "authorization",
            "label": "Authorization",
            "description": "抓包获得的 Basic Authorization，支持带或不带 Basic 前缀。",
            "input_type": "textarea",
            "required": False,
            "secret": True,
            "placeholder": "Basic xxxxx",
        },
        {
            "key": "cookie",
            "label": "Cookie",
            "description": "mail 登录 Cookie；可选填写用于辅助账号密码登录。",
            "input_type": "textarea",
            "required": False,
            "secret": True,
            "placeholder": "RMKEY=...; Os_SSo_Sid=...",
        },
        {
            "key": "username",
            "label": "手机号",
            "description": "139 登录手机号；账号密码登录时必填。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "13800138000",
        },
        {
            "key": "password",
            "label": "密码",
            "description": "139 账号密码登录使用的密码。",
            "input_type": "password",
            "required": False,
            "secret": True,
            "placeholder": "",
        },
        {
            "key": "lsdir_cache_path",
            "label": "缓存路径",
            "description": "lsdir 缓存刷新与网盘同步默认范围使用的根目录（网盘内路径）。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "/",
        },
        {
            "key": "strm_scan_path",
            "label": "STRM 扫描路径",
            "description": "STRM/CAS 使用的扫描根目录（网盘内路径）；支持英文逗号分隔多路径，为空时默认与缓存路径一致。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "/影视,/动漫",
        },
        {
            "key": "debug",
            "label": "调试模式",
            "description": "开启后输出更多调试日志。",
            "input_type": "switch",
            "required": False,
            "secret": False,
            "placeholder": "",
        },
    ]

    BASE_URL = "https://yun.139.com"
    USER_NJS_URL = "https://user-njs.yun.139.com"
    SHARE_KD_NJS_URL = "https://share-kd-njs.yun.139.com"
    PERSONAL_KD_NJS_URL = "https://personal-kd-njs.yun.139.com"
    CATALOG_V1 = f"{BASE_URL}/orchestration/personalCloud/catalog/v1.0"
    SIGN_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    PASSWORD_LOGIN_AES_KEY_HEX = "73634235495062495331515373756c734e7253306c673d3d"
    THIRD_LOGIN_INNER_AES_KEY_HEX = "7150714477323633586746674c337538"
    DEFAULT_HEADERS = {
        "Content-Type": "application/json",
        "x-yun-api-version": "v1",
        "x-yun-app-channel": "10000034",
        "x-yun-channel-source": "10000034",
        "x-yun-client-info": "||9|7.14.4|edge||||linux unknow||zh-CN|||",
        "x-yun-module-type": "100",
        "x-yun-svc-type": "1",
        "mcloud-channel": "1000101",
        "mcloud-version": "7.14.4",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Origin": "https://yun.139.com",
        "Referer": "https://yun.139.com/",
    }
    MARKET_USER_AGENT = (
        "Mozilla/5.0 (Linux; Android 11; M2012K10C Build/RP1A.200720.011; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/90.0.4430.210 "
        "Mobile Safari/537.36 MCloudApp/10.0.1"
    )
    MARKET_BASE_URL = "https://m.mcloud.139.com"
    MARKET_SOURCE_ID = "1097"
    SIGNIN_ACTIVITY_ID = "sign_in_3"
    MAIL_SIGNIN_ACTIVITY_ID = "newsign_139mail"
    SIGN_IN_TOTAL_BUDGET_SECONDS = 40.0
    SIGN_IN_STAGE_MIN_SECONDS = 1.5
    REFRESH_TOKEN_AES_KEY = "c7lXOigXahPnTViq"
    CLOUD_FILE_DUMMY_CONTENT = b"0"
    CLOUD_FILE_DUMMY_HASH = hashlib.sha256(CLOUD_FILE_DUMMY_CONTENT).hexdigest()
    RED_PACKET_SOURCE_ID = "001216"
    RED_PACKET_VERSION = "SYS_CONFIG_Y"
    RED_PACKET_BASE_URL = "https://cpactiv.buy.139.com/cloudphone-market"
    RED_PACKET_PAGE_URL = "https://cpactiv.buy.139.com/#/redEnvelopeParty/home?channelSrc=red-cmccapp"
    RED_PACKET_APP_ID = "12345681"
    RED_PACKET_SIGN_KEY = "e10adc3949ba59abbe56e057f20f883e"
    RED_PACKET_CHANNEL_SRC = "red-cmccapp"
    FRUIT_BASE_URL = "https://happy.mail.10086.cn/jsp/cn/garden/"
    FRUIT_SOURCE_ID = "1003"
    FRUIT_TARGET_SOURCE_ID = "001208"
    RED_PACKET_BROWSE_TASKS = {"NOVICE_2", "NOVICE_3", "MONTHLY_1"}
    RED_PACKET_DIRECT_TASKS = {"MONTHLY_4", "MONTHLY_5"}
    RED_PACKET_MANUAL_TASKS = {"NOVICE_1": "需跳转领取定向流量"}
    RED_PACKET_KNOWN_ANSWERS = {
        "如何查看并更新移动云手机客户端最新版本？": '进入"我的"-点击"关于云手机"-点击"检查新版本"',
        "移动云手机可领取定向流量，每月赠送的定向流量是（  ）。": "30GB",
        "移动云手机端内订购的专业版分辨率已升级到1080P，该说法是否正确？": "正确",
        "移动云手机支持视频录制，该说法是否正确？": "正确",
        "云手机支持通过手机、平板、电脑等多种终端设备登录使用，该说法是否正确？": "正确",
        "使用中国移动号码登录移动云手机，是否支持手机号一键登录？": "支持",
        "只有中国移动运营商号码能使用移动云手机？": "不正确",
        "移动云手机是否需要充电使用？": "不需要",
        "移动云手机支持截图，该说法是否正确？": "正确",
        "移动云手机AI灵犀助手已接入DeepSeek，是否正确？": "正确",
        "移动云手机内支持画面清晰度切换，该说法是否正确？": "正确",
        "移动云手机支持连接蓝牙使用吗？": "不支持",
        "在云手机内安装游戏应用是否占本地手机存储空间？": "否，不占本地空间",
        "如何更换云机内的桌面主题或壁纸？": "云机内-【设置】-壁纸/个性主题",
        "如何将云手机里的应用添加至本地手机桌面？": "云手机桌面-长按应用-发送图标到本地",
    }
    AI_CAMERA_SAMPLE_BASE64 = (
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxAQDxAPEA8QDw8PEA8PDw8PDw8PDw8QFREWFhUR"
        "FRUYHSggGBolGxUVITEhJSkrLi4uFx8zODMsNygtLisBCgoKDg0OGxAQGy0lICYtLS0tLS0tLS0t"
        "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAAEAAQMBIgACEQEDEQH/xAAX"
        "AAADAQAAAAAAAAAAAAAAAAAAAQMC/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEAMQAAAB"
        "6gD/xAAVEAEBAAAAAAAAAAAAAAAAAAABAP/aAAgBAQABBQJf/8QAFBEBAAAAAAAAAAAAAAAAAAAA"
        "AP/aAAgBAwEBPwEf/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwEf/8QAFBABAAAAAAAA"
        "AAAAAAAAAAAAAP/aAAgBAQAGPwJf/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyFf/9k="
    )
    _SM_PUBLIC_KEY = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC8KHAcHbkCn5rxGgGJE+07tY+pt86D/oZ7sA51FaEBv2jgno2TI9zHJVYKJynmiKpixgwUcv93EfWIrU/p/UCs5Vu+odS3I4UBp3R7IZ1A0W01FkumAHYW2PQpMm8ueQKPLUq/idkpG/9b2JDv/qU+Ks36nbUPwlW4CjdfrV+V9QIDAQAB"
    _SM_ORGANIZATION = "FXlyfmWg2AzwbrxDKSv5"
    _SM_ANDROID_MODELS = [
        {"model": "23127HN0CC", "build": "UKQ1.230917.001", "android": "14", "chrome": "143.0.7499.146"},
        {"model": "24053PY09C", "build": "UP1A.231005.007", "android": "14", "chrome": "142.0.6522.118"},
        {"model": "23049RAD8C", "build": "TKQ1.221114.001", "android": "13", "chrome": "143.0.7499.146"},
        {"model": "PGP110", "build": "UKQ1.230917.001", "android": "14", "chrome": "141.0.6464.127"},
        {"model": "RMXP4721", "build": "UKQ1.230917.001", "android": "14", "chrome": "143.0.7499.146"},
        {"model": "M2012K10C", "build": "RP1A.200720.011", "android": "11", "chrome": "142.0.6522.118"},
        {"model": "V2324A", "build": "UP1A.231005.007", "android": "14", "chrome": "143.0.7499.146"},
        {"model": "RE58B1", "build": "TKQ1.221114.001", "android": "13", "chrome": "140.0.6385.82"},
        {"model": "22081212C", "build": "UKQ1.230917.001", "android": "14", "chrome": "143.0.7499.146"},
        {"model": "LLY-AN00", "build": "HONORLLY-AN00", "android": "14", "chrome": "142.0.6522.118"},
    ]
    _SM_SCREENS = [
        {"w": 1080, "h": 2340, "dpr": 2.625},
        {"w": 1080, "h": 2400, "dpr": 2.75},
        {"w": 720, "h": 1280, "dpr": 1.5},
        {"w": 1080, "h": 2160, "dpr": 2.625},
        {"w": 1080, "h": 2310, "dpr": 2.625},
    ]

    def __init__(
        self,
        cookie: str = "",
        index: int = 0,
        config: dict[str, Any] | None = None,
        account_name: str = "",
        no_login: bool = False,
    ):
        super().__init__(cookie, index, config=config, no_login=no_login)
        self._cfg = dict(self.config or {})
        self._authorization = str(self._cfg.get("authorization") or "").strip()
        self._cookie_value = str(self._cfg.get("cookie") or "").strip()
        self._username = str(self._cfg.get("username") or self._cfg.get("phone") or "").strip()
        self._password = str(self._cfg.get("password") or "").strip()
        self._phone = self._username
        self._account_name = account_name or f"cloud139用户{self.index}"
        self._debug = bool(self._cfg.get("debug"))
        self._user_cache: dict[str, Any] | None = None
        self._account = ""
        self._user_domain_id = ""

        self._session = requests.Session()
        self._session.headers.update(dict(self.DEFAULT_HEADERS))
        self._market_session = requests.Session()
        self._apply_auth_headers()
        if self._debug:
            logger.setLevel(logging.DEBUG)
        self._market_device_id = ""
        self._market_jwt_token = ""
        self._market_sso_token = ""
        self._market_session_prepared = False
        self._red_packet_token = ""
        self._red_packet_mobile = ""
        self._red_packet_jwt_token = ""
        self._sign_in_deadline_ts: float | None = None

    @staticmethod
    def _md5(value: str) -> str:
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _sha1_hex(value: str) -> str:
        return hashlib.sha1(value.encode("utf-8")).hexdigest()

    @classmethod
    def _random_str(cls, n: int = 16) -> str:
        return "".join(random.choice(cls.SIGN_CHARS) for _ in range(n))

    @staticmethod
    def _format_datetime_cst() -> str:
        cst = datetime.fromtimestamp(time.time() + 8 * 3600)
        return cst.strftime("%Y-%m-%d %H:%M:%S")

    def _get_new_sign_hash(self, body: dict[str, Any] | None, datetime_cst: str, random_str: str) -> str:
        raw = ""
        if body:
            raw = json.dumps(dict(body), ensure_ascii=False, separators=(",", ":"))
            raw = quote(raw, safe="")
            raw = "".join(sorted(raw))
        b64 = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
        r = self._md5(b64)
        c = self._md5(f"{datetime_cst}:{random_str}")
        return self._md5(r + c).upper()

    def _compute_mcloud_sign(self, catalog_id: str) -> str:
        datetime_cst = self._format_datetime_cst()
        random_str = self._random_str(16)
        get_disk_body = {
            "catalogID": catalog_id or "/",
            "sortDirection": 1,
            "startNumber": 1,
            "endNumber": 100,
            "filterType": 0,
            "catalogSortType": 0,
            "contentSortType": 0,
            "commonAccountInfo": self._account_payload(),
        }
        sign_hash = self._get_new_sign_hash(get_disk_body, datetime_cst, random_str)
        return f"{datetime_cst},{random_str},{sign_hash}"

    def _normalize_basic_auth(self, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        return raw if re.match(r"^Basic\s+", raw, flags=re.I) else f"Basic {raw}"

    def _decode_basic_auth_parts(self, value: str) -> list[str]:
        auth = self._normalize_basic_auth(value)
        if not auth:
            return []
        try:
            raw = re.sub(r"^Basic\s+", "", auth, flags=re.I)
            padded = raw + ("=" * ((4 - len(raw) % 4) % 4))
            decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        except Exception:
            return []
        return decoded.split(":")

    def _is_basic_auth_str(self, value: str) -> bool:
        raw = str(value or "").strip()
        if not raw:
            return False
        return bool(re.match(r"^Basic\s+", raw, flags=re.I) or re.fullmatch(r"[A-Za-z0-9+/]+=*", raw))

    def _parse_phone_from_authorization(self, value: str) -> str:
        parts = self._decode_basic_auth_parts(value)
        if len(parts) >= 2 and re.fullmatch(r"1\d{10}", parts[1] or ""):
            return str(parts[1] or "")
        return ""

    def _apply_auth_headers(self) -> None:
        self._session.headers.pop("Authorization", None)
        self._session.headers.pop("Cookie", None)
        auth = self._normalize_basic_auth(self._authorization)
        if auth:
            self._session.headers["Authorization"] = auth
            parsed_phone = self._parse_phone_from_authorization(auth)
            if parsed_phone:
                self._username = parsed_phone
                self._phone = parsed_phone
        elif self._cookie_value:
            self._session.headers["Cookie"] = self._cookie_value
        else:
            # 保持空会话，init 时再提示未配置认证信息。
            pass

    @staticmethod
    def _parse_cookie_string(cookie_value: str) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for chunk in str(cookie_value or "").split(";"):
            item = chunk.strip()
            if not item or "=" not in item:
                continue
            key, value = item.split("=", 1)
            parsed[key.strip()] = value.strip()
        return parsed

    @classmethod
    def _merge_cookie_values(cls, *cookie_values: str) -> str:
        merged: dict[str, str] = {}
        for cookie_value in cookie_values:
            merged.update(cls._parse_cookie_string(cookie_value))
        return "; ".join(f"{key}={value}" for key, value in merged.items() if key and value)

    def _update_cookie_value(self, cookie_value: str) -> None:
        merged = self._merge_cookie_values(self._cookie_value, cookie_value)
        if merged:
            self._cookie_value = merged
        self._apply_auth_headers()

    def _account_payload(self) -> dict[str, Any]:
        account = self._username or self._phone or self._parse_phone_from_authorization(self._authorization)
        return {"account": account or "", "accountType": 1}

    @staticmethod
    def _pkcs7_pad(data: bytes, block_size: int) -> bytes:
        padding = block_size - (len(data) % block_size)
        return data + bytes([padding] * padding)

    @staticmethod
    def _pkcs7_unpad(data: bytes) -> bytes:
        if not data:
            raise ValueError("empty data")
        padding = data[-1]
        if padding <= 0 or padding > len(data):
            raise ValueError("invalid padding")
        if data[-padding:] != bytes([padding] * padding):
            raise ValueError("invalid padding bytes")
        return data[:-padding]

    @staticmethod
    def _aes_cbc_encrypt(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        return encryptor.update(Cloud139Adapter._pkcs7_pad(plaintext, algorithms.AES.block_size // 8)) + encryptor.finalize()

    @staticmethod
    def _aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        return Cloud139Adapter._pkcs7_unpad(decryptor.update(ciphertext) + decryptor.finalize())

    @staticmethod
    def _aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        decryptor = cipher.decryptor()
        return Cloud139Adapter._pkcs7_unpad(decryptor.update(ciphertext) + decryptor.finalize())

    @staticmethod
    def _aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
        encryptor = cipher.encryptor()
        return encryptor.update(Cloud139Adapter._pkcs7_pad(plaintext, algorithms.AES.block_size // 8)) + encryptor.finalize()

    @classmethod
    def _sorted_json_stringify(cls, obj: Any) -> str:
        if obj is None:
            return "null"
        if isinstance(obj, bool):
            return "true" if obj else "false"
        if isinstance(obj, (int, float)):
            return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        if isinstance(obj, str):
            return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        if isinstance(obj, list):
            return "[" + ",".join(cls._sorted_json_stringify(item) for item in obj) + "]"
        if isinstance(obj, tuple):
            return "[" + ",".join(cls._sorted_json_stringify(item) for item in obj) + "]"
        if isinstance(obj, dict):
            items = []
            for key in sorted(obj.keys()):
                items.append(
                    f"{json.dumps(str(key), ensure_ascii=False, separators=(',', ':'))}:{cls._sorted_json_stringify(obj[key])}"
                )
            return "{" + ",".join(items) + "}"
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    def _encrypted_request(
        self,
        req_url: str,
        body: dict[str, Any],
        headers: dict[str, str],
        aes_key_hex: str,
    ) -> bytes:
        try:
            aes_key = binascii.unhexlify(aes_key_hex)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError("解码 AES Key 失败") from exc
        payload_text = self._sorted_json_stringify(body)
        iv = os.urandom(16)
        encrypted = self._aes_cbc_encrypt(payload_text.encode("utf-8"), aes_key, iv)
        request_payload = base64.b64encode(iv + encrypted).decode("utf-8")

        self._throttle_request()
        resp = self._session.request(
            method="POST",
            url=req_url,
            data=request_payload,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        response_bytes = resp.content or b""
        if response_bytes.startswith(b"{"):
            return response_bytes
        try:
            decoded = base64.b64decode(response_bytes)
        except Exception as exc:
            raise RuntimeError("解析加密响应失败") from exc
        if len(decoded) < 16:
            raise RuntimeError("加密响应内容过短")
        resp_iv = decoded[:16]
        resp_ciphertext = decoded[16:]
        return self._aes_cbc_decrypt(resp_ciphertext, aes_key, resp_iv)

    def _password_login_headers(self, cguid: str) -> dict[str, str]:
        referer = (
            "https://mail.10086.cn/default.html?&s=1&v=0&u="
            f"{base64.b64encode((self._username or '').encode('utf-8')).decode('utf-8')}"
            f"&m=1&ec=S001&resource=indexLogin&clientid=1003&auto=on&cguid={cguid}&mtime=45"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://mail.10086.cn",
            "Referer": referer,
            "User-Agent": self.DEFAULT_HEADERS["User-Agent"],
        }
        if self._cookie_value:
            headers["Cookie"] = self._cookie_value
        return headers

    def _step1_password_login(self) -> str:
        if not self._username or not self._password:
            raise RuntimeError("账号密码不能为空")
        hashed_password = self._sha1_hex(f"fetion.com.cn:{self._password}")
        cguid = str(int(time.time() * 1000))
        form = {
            "UserName": self._username,
            "passOld": "",
            "auto": "on",
            "Password": hashed_password,
            "webIndexPagePwdLogin": "1",
            "pwdType": "1",
            "clientId": "1003",
            "authType": "2",
        }
        self._throttle_request()
        resp = self._session.request(
            method="POST",
            url="https://mail.10086.cn/Login/Login.ashx",
            data=form,
            headers=self._password_login_headers(cguid),
            timeout=30,
            allow_redirects=False,
        )
        resp.raise_for_status()

        cookie_pairs = [f"{cookie.name}={cookie.value}" for cookie in resp.cookies]
        if cookie_pairs:
            self._update_cookie_value("; ".join(cookie_pairs))

        sid = ""
        location = str(resp.headers.get("Location") or "")
        if location:
            match = re.search(r"sid=([^&]+)", location)
            if match:
                sid = str(match.group(1) or "")

        if not sid:
            sid = self._parse_cookie_string(self._cookie_value).get("Os_SSo_Sid", "")
        if not sid:
            raise RuntimeError("密码登录失败，未获取到 sid")
        return sid

    def _step2_get_artifact(self, sid: str) -> str:
        cookie_map = self._parse_cookie_string(self._cookie_value)
        rmkey = str(cookie_map.get("RMKEY") or "")
        if not rmkey:
            raise RuntimeError("密码登录失败，缺少 RMKEY")
        cookie_header = self._cookie_value.strip() or f"RMKEY={rmkey}"
        cguid = str(int(time.time() * 1000))
        url = (
            "https://smsrebuild1.mail.10086.cn/setting/s?"
            f"func={quote('umc:getArtifact', safe='')}&sid={quote(sid, safe='')}&cguid={cguid}"
        )
        headers = {
            "Host": "smsrebuild1.mail.10086.cn",
            "Cookie": cookie_header,
            "Content-Type": "text/xml; charset=utf-8",
            "Accept-Encoding": "gzip",
            "User-Agent": "okhttp/4.12.0",
        }

        self._throttle_request()
        resp = self._session.request(
            method="POST",
            url=url,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.content or b""
        artifact = ""
        try:
            payload = resp.json()
            artifact = str((((payload or {}).get("var") or {}).get("artifact")) or "")
        except Exception:
            text = body.decode("utf-8", errors="ignore")
            match = re.search(r'"artifact"\s*:\s*"([^"]+)"', text)
            if match:
                artifact = str(match.group(1) or "")
        if not artifact:
            raise RuntimeError("密码登录失败，未获取到 artifact")
        return artifact

    def _step3_third_party_login(self, artifact: str) -> str:
        headers = {
            "hcy-cool-flag": "1",
            "x-huawei-channelSrc": "10246600",
            "x-sdk-channelSrc": "",
            "x-MM-Source": "0",
            "x-UserAgent": "android|23116PN5BC|android15|1.2.6|||1440x3200|10246600",
            "x-DeviceInfo": "4|127.0.0.1|5|1.2.6|Xiaomi|23116PN5BC||02-00-00-00-00-00|android 15|1440x3200|android|||",
            "Content-Type": "text/plain;charset=UTF-8",
            "Host": "user-njs.yun.139.com",
            "Accept-Encoding": "gzip",
            "User-Agent": "okhttp/3.12.2",
        }
        request_body = {
            "clientkey_decrypt": "l3TryM&Q+X7@dzwk)qP",
            "clienttype": "886",
            "cpid": "507",
            "dycpwd": artifact,
            "extInfo": {"ifOpenAccount": "0"},
            "loginMode": "0",
            "msisdn": self._username,
            "pintype": "13",
            "secinfo": self._sha1_hex(f"fetion.com.cn:{artifact}").upper(),
            "version": "20250901",
        }
        decrypted = self._encrypted_request(
            "https://user-njs.yun.139.com/user/thirdlogin",
            request_body,
            headers,
            self.PASSWORD_LOGIN_AES_KEY_HEX,
        )
        try:
            first_layer = json.loads(decrypted.decode("utf-8", errors="ignore"))
        except Exception as exc:
            raise RuntimeError("解析 thirdlogin 第一层响应失败") from exc
        hex_inner = str((first_layer or {}).get("data") or "")
        if not hex_inner:
            raise RuntimeError("thirdlogin 响应缺少 data 字段")
        try:
            inner_ciphertext = binascii.unhexlify(hex_inner)
            inner_key = binascii.unhexlify(self.THIRD_LOGIN_INNER_AES_KEY_HEX)
            final_bytes = self._aes_ecb_decrypt(inner_ciphertext, inner_key)
            final_payload = json.loads(final_bytes.decode("utf-8", errors="ignore"))
        except Exception as exc:
            raise RuntimeError("解析 thirdlogin 第二层响应失败") from exc

        auth_token = str((final_payload or {}).get("authToken") or "")
        account = str((final_payload or {}).get("account") or self._username or "")
        user_domain_id = str((final_payload or {}).get("userDomainId") or "")
        if not auth_token or not account:
            raise RuntimeError("thirdlogin 响应缺少 authToken 或 account")
        self._account = account
        self._user_domain_id = user_domain_id
        self._username = account
        self._phone = account
        auth_raw = base64.b64encode(f"pc:{account}:{auth_token}".encode("utf-8")).decode("utf-8")
        self._authorization = self._normalize_basic_auth(auth_raw)
        self._apply_auth_headers()
        return self._authorization

    def _login_with_password(self) -> str:
        sid = self._step1_password_login()
        artifact = self._step2_get_artifact(sid)
        return self._step3_third_party_login(artifact)

    def _refresh_authorization_token(self) -> str:
        parts = self._decode_basic_auth_parts(self._authorization)
        if len(parts) < 3:
            raise RuntimeError("authorization 格式无效")
        account = str(parts[1] or "")
        token = str(parts[2] or "")
        token_segments = token.split("|")
        if len(token_segments) >= 4:
            try:
                expiration = int(token_segments[3])
                if expiration - int(time.time() * 1000) > 5 * 24 * 60 * 60 * 1000:
                    return self._normalize_basic_auth(self._authorization)
                if expiration <= int(time.time() * 1000):
                    raise RuntimeError("authorization 已过期")
            except ValueError:
                pass
        try:
            refresh_headers = {
                "Content-Type": "application/json",
                "User-Agent": self.MARKET_USER_AGENT,
                "x-yun-tid": self._random_str(8) + "-" + self._random_str(4) + "-4" + self._random_str(3) + "-" + random.choice("89ab") + self._random_str(3) + "-" + self._random_str(12),
                "Authorization": self._normalize_basic_auth(self._authorization),
                "x-yun-api-version": "v1",
                "x-yun-module-type": "100",
                "x-yun-op-type": "1",
                "x-yun-app-channel": "10214200",
                "x-yun-client-info": "||8||||||||||||",
                "hcy-cool-flag": "1",
            }
            if self._user_domain_id:
                refresh_headers["x-yun-uni"] = self._user_domain_id
            payload = {"phoneNumber": account}
            encrypted = base64.b64encode(
                self._aes_ecb_encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), self.REFRESH_TOKEN_AES_KEY.encode("utf-8"))
            ).decode("utf-8")
            refresh_resp = self._request_json(
                "POST",
                f"{self.USER_NJS_URL}/user/auth/refreshToken",
                headers=refresh_headers,
                json_body={"data": encrypted},
                timeout=30,
            )
            code = str((refresh_resp or {}).get("code") or "")
            data = (refresh_resp or {}).get("data") or {}
            success = bool((refresh_resp or {}).get("success"))
            ok = code in ("0", "00", "000", "0000") or success or (code.startswith("0") and len(code) <= 4)
            new_token = str((data or {}).get("token") or "")
            if ok and new_token:
                auth_type = str(parts[0] or "mobile")
                new_auth_raw = base64.b64encode(f"{auth_type}:{account}:{new_token}".encode("utf-8")).decode("utf-8")
                self._authorization = self._normalize_basic_auth(new_auth_raw)
                self._account = account
                if re.fullmatch(r"1\d{10}", account):
                    self._username = account
                    self._phone = account
                self._apply_auth_headers()
                return self._authorization
        except Exception as exc:
            self._debug_log_json("auth.refresh_new_failed", {"message": str(exc)})
        req_body = (
            f"<root><token>{token}</token><account>{account}</account>"
            "<clienttype>656</clienttype></root>"
        )
        headers = {
            "Content-Type": "application/xml",
            "User-Agent": self.DEFAULT_HEADERS["User-Agent"],
        }
        self._throttle_request()
        resp = self._session.request(
            method="POST",
            url="https://aas.caiyun.feixin.10086.cn:443/tellin/authTokenRefresh.do",
            data=req_body,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.text or ""
        return_code = re.search(r"<return>([^<]+)</return>", text)
        refreshed_token = re.search(r"<token>([^<]+)</token>", text)
        if not return_code or str(return_code.group(1) or "") != "0" or not refreshed_token:
            raise RuntimeError("authorization 刷新失败")
        new_token = str(refreshed_token.group(1) or "")
        new_auth_raw = base64.b64encode(f"{parts[0]}:{account}:{new_token}".encode("utf-8")).decode("utf-8")
        self._authorization = self._normalize_basic_auth(new_auth_raw)
        self._account = account
        if re.fullmatch(r"1\d{10}", account):
            self._username = account
            self._phone = account
        self._apply_auth_headers()
        return self._authorization

    def _ensure_authenticated(self) -> None:
        if self._authorization:
            try:
                self._refresh_authorization_token()
                return
            except Exception as exc:
                self._debug_log_json("auth.refresh_failed", {"message": str(exc)})
                self._apply_auth_headers()
                if self._username and self._password:
                    self._login_with_password()
                return
        if self._username and self._password:
            self._login_with_password()
            return
        if self._cookie_value:
            self._apply_auth_headers()
            return
        raise RuntimeError("未配置 authorization、cookie 或账号密码")

    def _update_identity_from_user_info(self, info: dict[str, Any]) -> None:
        account = str(info.get("account") or self._account or self._username or "").strip()
        if account:
            self._account = account
            if re.fullmatch(r"1\d{10}", account):
                self._username = account
                self._phone = account
        user_domain_id = str(info.get("userDomainId") or self._user_domain_id or "").strip()
        if user_domain_id:
            self._user_domain_id = user_domain_id

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: Any = None,
        cookies: dict[str, str] | None = None,
        timeout: int | float = 20,
        session: requests.Session | None = None,
    ) -> Any:
        self._throttle_request()
        client = session or self._session
        effective_timeout = self._effective_timeout(float(timeout))
        request_kwargs: dict[str, Any] = {
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
            "cookies": cookies,
            "timeout": effective_timeout,
        }
        if data is None:
            request_kwargs["json"] = json_body
        else:
            request_kwargs["data"] = data
        resp = client.request(**request_kwargs)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception as exc:
            raise RuntimeError((resp.text or "").strip()[:300] or "响应解析失败") from exc

    def _request_text(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        data: Any = None,
        cookies: dict[str, str] | None = None,
        timeout: int | float = 20,
        session: requests.Session | None = None,
    ) -> str:
        self._throttle_request()
        client = session or self._session
        effective_timeout = self._effective_timeout(float(timeout))
        resp = client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            data=data,
            cookies=cookies,
            timeout=effective_timeout,
        )
        resp.raise_for_status()
        return resp.text or ""

    def _market_request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        cookies: dict[str, str] | None = None,
        timeout: int | float = 20,
    ) -> Any:
        return self._request_json(
            method,
            url,
            headers=headers,
            params=params,
            json_body=json_body,
            cookies=cookies,
            timeout=timeout,
            session=self._market_session,
        )

    def _debug_log_json(self, tag: str, payload: Any) -> None:
        if not self._debug:
            return
        try:
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            text = str(payload)
        logger.warning("[cloud139][raw][%s] %s", tag, text[:12000])

    def _user_njs_post(self, path: str, body: dict[str, Any]) -> Any:
        headers = {
            "caller": "web",
            "x-m4c-caller": "PC",
            "x-m4c-src": "10002",
            "x-inner-ntwk": "2",
            "mcloud-route": "001",
            "mcloud-version": "7.17.2",
            "mcloud-channel": "1000101",
            "mcloud-client": "10701",
            "INNER-HCY-ROUTER-HTTPS": "1",
        }
        payload = self._request_json("POST", f"{self.USER_NJS_URL}{path}", headers=headers, json_body=body)
        code = str((payload or {}).get("code") or "")
        if code not in ("", "0", "0000"):
            raise RuntimeError((payload or {}).get("desc") or (payload or {}).get("message") or f"user-njs 错误: {code}")
        return (payload or {}).get("data") if isinstance(payload, dict) and "data" in payload else payload

    def _share_kd_post(self, path: str, body: dict[str, Any]) -> Any:
        headers = {
            "caller": "web",
            "x-m4c-caller": "PC",
            "mcloud-client": "10701",
            "mcloud-version": "7.17.2",
            "mcloud-channel": "1000101",
        }
        payload = self._request_json("POST", f"{self.SHARE_KD_NJS_URL}{path}", headers=headers, json_body=body)
        code = str((payload or {}).get("code") or "")
        if code not in ("", "0", "0000"):
            raise RuntimeError((payload or {}).get("desc") or (payload or {}).get("message") or f"share 接口错误: {code}")
        return (payload or {}).get("data") if isinstance(payload, dict) and "data" in payload else payload

    def _personal_kd_post(self, path: str, body: dict[str, Any], sign_catalog_id: str = "/") -> Any:
        headers = {
            "caller": "web",
            "mcloud-version": "7.17.2",
            "mcloud-channel": "1000101",
            "mcloud-client": "10701",
            "mcloud-route": "001",
            "mcloud-sign": self._compute_mcloud_sign(sign_catalog_id or "/"),
            "INNER-HCY-ROUTER-HTTPS": "1",
            "x-m4c-caller": "PC",
            "x-m4c-src": "10002",
            "x-inner-ntwk": "2",
            "x-yun-channel-source": "10000034",
            "x-huawei-channelSrc": "10000034",
            "x-yun-svc-type": "1",
            "x-SvcType": "1",
            "x-yun-module-type": "100",
            "x-yun-app-channel": "10000034",
            "x-yun-api-version": "v1",
            "x-yun-client-info": "||9|7.17.2|chrome|143.0.0.0|python-port||linux||zh-CN|||",
            "X-Deviceinfo": "||9|7.17.2|chrome|143.0.0.0|python-port||linux||zh-CN|||",
            "CMS-DEVICE": "default",
        }
        payload = self._request_json("POST", f"{self.PERSONAL_KD_NJS_URL}{path}", headers=headers, json_body=body)
        code = str((payload or {}).get("code") or "")
        success = bool((payload or {}).get("success"))
        if not success and code not in ("", "0", "0000"):
            raise RuntimeError((payload or {}).get("desc") or (payload or {}).get("message") or f"hcy 接口错误: {code}")
        return (payload or {}).get("data") if isinstance(payload, dict) and "data" in payload else payload

    def _get_user_info(self) -> dict[str, Any]:
        if self._user_cache is not None:
            return dict(self._user_cache)
        data = self._user_njs_post("/user/getUser", {})
        if not isinstance(data, dict):
            raise RuntimeError("获取 139 用户信息失败")
        self._user_cache = dict(data)
        self._update_identity_from_user_info(self._user_cache)
        return dict(data)

    def _get_disk_info(self) -> dict[str, Any]:
        user_info = self._get_user_info()
        user_domain_id = str(user_info.get("userDomainId") or "").strip()
        if not user_domain_id:
            return {}
        data = self._user_njs_post("/user/disk/getPersonalDiskInfo", {"userDomainId": user_domain_id})
        return data if isinstance(data, dict) else {}

    def init(self) -> Any:
        if not (self._authorization or self._cookie_value or (self._username and self._password)):
            return False
        try:
            self._ensure_authenticated()
            info = self._get_user_info()
        except Exception as exc:
            logger.warning("[cloud139] init failed: %s", exc)
            self.is_active = False
            return False
        self.is_active = True
        self._update_identity_from_user_info(info)
        self.nickname = str(info.get("nickName") or info.get("nickname") or self._username or self._account_name)
        return info

    def get_account_config(self) -> Dict[str, Any]:
        try:
            info = self._get_user_info()
            disk_info = self._get_disk_info()
        except Exception:
            info = {}
            disk_info = {}
        total_mb = int(disk_info.get("diskSize") or 0) if str(disk_info.get("diskSize") or "").isdigit() else 0
        free_mb = int(disk_info.get("freeDiskSize") or 0) if str(disk_info.get("freeDiskSize") or "").isdigit() else 0
        mb = 1024 * 1024
        used_space = max(total_mb - free_mb, 0) * mb if total_mb else None
        total_space = total_mb * mb if total_mb else None
        nickname = str(info.get("nickName") or info.get("nickname") or self.nickname or self._phone or self._account_name)
        self.nickname = nickname
        return {
            "drive_type": self.DRIVE_TYPE,
            "drive_name": self.DRIVE_NAME,
            "nickname": nickname,
            "username": str(info.get("account") or self._username or nickname),
            "used_space": used_space,
            "total_space": total_space,
            "raw": {
                "user_info": info or None,
                "disk_info": disk_info or None,
            },
        }

    def export_runtime_config(self) -> dict[str, Any]:
        return {
            "authorization": self._normalize_basic_auth(self._authorization),
            "cookie": self._cookie_value,
            "username": self._username or self._phone,
            "password": self._password,
            "debug": self._debug,
        }

    def _market_headers(self, *, include_jwt: bool = False, jwt_token: str = "") -> dict[str, str]:
        headers = {
            "User-Agent": self.MARKET_USER_AGENT,
            "Accept": "*/*",
            "X-Requested-With": "com.chinamobile.mcloud",
            "Referer": self._build_market_page_url(),
        }
        if include_jwt and jwt_token:
            headers["jwtToken"] = jwt_token
        device_id = self._get_market_device_id()
        if device_id:
            headers["deviceId"] = device_id
        return headers

    def _market_cookies(self, jwt_token: str = "") -> dict[str, str]:
        cookies = {
            "sensors_stay_time": str(int(time.time() * 1000)),
        }
        if jwt_token:
            cookies["jwtToken"] = jwt_token
        if self._user_domain_id:
            cookies["userDomainId"] = self._user_domain_id
        return cookies

    @staticmethod
    def _current_millis() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _extract_user_domain_id(jwt_token: str) -> str:
        try:
            payload = jwt_token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
            sub = data.get("sub", "")
            if isinstance(sub, str):
                sub = json.loads(sub)
            if isinstance(sub, dict):
                return str(sub.get("userDomainId") or "")
        except Exception:
            return ""
        return ""

    @classmethod
    def _sm_rsa_encrypt(cls, plaintext: str) -> str:
        public_key = load_der_public_key(base64.b64decode(cls._SM_PUBLIC_KEY), backend=default_backend())
        encrypted = public_key.encrypt(plaintext.encode("utf-8"), asym_padding.PKCS1v15())
        return base64.b64encode(encrypted).decode("ascii")

    @staticmethod
    def _sm_get_smid(uid: str) -> str:
        now = datetime.now()
        ts = now.strftime("%Y%m%d%H%M%S")
        md5_uid = hashlib.md5(uid.encode("utf-8")).hexdigest()
        base_str = ts + md5_uid + "00"
        check = hashlib.md5(("smsk_web_" + base_str).encode("utf-8")).hexdigest()[:14]
        return base_str + check + "0"

    @classmethod
    def _generate_market_device_profile(cls) -> str:
        phone = random.choice(cls._SM_ANDROID_MODELS)
        screen = random.choice(cls._SM_SCREENS)
        ua = (
            f"Mozilla/5.0 (Linux; Android {phone['android']}; {phone['model']} Build/{phone['build']}; wv) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{phone['chrome']} "
            "Mobile Safari/537.36 MCloudApp/13.0.0 AppLanguage/zh-CN"
        )
        sw, sh = screen["w"], screen["h"]
        avail_h = sh - random.randint(48, 128)
        uid = f"{cls._random_str(8)}-{cls._random_str(4)}-{cls._random_str(4)}-{cls._random_str(4)}-{cls._random_str(12)}"
        ep = cls._sm_rsa_encrypt(uid)
        smid = cls._sm_get_smid(uid)
        now_ts = int(time.time() * 1000)
        start_time = now_ts - random.randint(1800000, 5400000)
        now_cst = datetime.now(timezone(timedelta(hours=8)))
        env = {
            "protocol": 242, "organization": cls._SM_ORGANIZATION, "appId": "default",
            "os": "web", "version": "3.0.0", "sdkver": "3.0.0", "box": "",
            "rtype": "all", "smid": smid, "subVersion": "1.0.0",
            "time": now_ts - start_time, "cdp": 0, "maxTouchPoints": 5, "connectionRtt": 0, "cpucount": 8,
            "battery": {"charging": 0, "level": round(0.6 + random.random() * 0.35, 2)},
            "dg": "5.0 " + ua[len("Mozilla/"):], "gj": "zh-CN", "rr": "Google Inc.", "sv": "Netscape", "qc": "Mozilla",
            "ye": 8, "jq": 8, "lo": [], "bw": "", "lr": "Etc/GMT-8", "nr": 1, "no": 0, "br": 1, "ra": 0,
            "gt": sw, "wy": sw, "cj": avail_h, "wt": random.randint(100, 180), "hu": ["chrome"],
            "documentExist": 1, "yi": ["location"], "dx": "UTF-8",
            "ig": now_cst.strftime("%a %b %d %Y %H:%M:%S ") + "(GMT+08:00)", "ii": 1, "fs": 0, "ga": 0,
            "tk": 0, "rm": 0, "kr": 0, "nk": 0, "by": "srgb", "ar": 0, "or": 0, "et": 0, "zc": 0, "fj": 0,
            "dc": 0, "vd": 0, "ni": "", "hn": "", "hv": "48000_2_1_0_2_explicit_speakers|______",
            "de": hashlib.md5(uid.encode("utf-8")).hexdigest()[:16] + "|10011011111000111100001100101101111100110101001110000000000100000",
            "xt": 1, "vh": 0, "xc": {"red": "0"},
            "pm": {
                "default": round(120.5 + random.random() * 20, 1),
                "apple": round(120.5 + random.random() * 20, 1),
                "serif": round(100 + random.random() * 20, 1),
                "sans": round(120.5 + random.random() * 20, 1),
                "mono": round(100 + random.random() * 20, 1),
                "min": round(10 + random.random() * 2, 1),
                "system": round(120.5 + random.random() * 20, 1),
            },
            "ob": {"maxTouchPoints": 5, "touchEvent": True, "touchStart": True},
            "incognito": {
                "getDirectoryExist": 0, "getDirectoryIncognito": 0, "maxTouchPointsExist": 1,
                "indexedDBIncognito": 0, "openDatabaseExist": 0, "openDatabaseIncognito": 0,
                "localStorageExist": 1, "localStorageIncognito": 0, "promiseExist": 1,
                "promiseAllSettledExist": 1, "queryUsageAndQuotaIncognito": 0,
                "webkitRequestFileSystemIncognito": 0, "serviceWorkerExist": 1,
                "indexedDBExist": 1, "browserName": "Chrome",
            },
            "t": now_cst.strftime("%a %b %d %Y %H:%M:%S GMT+0800 (GMT+08:00)"),
            "collectTime": random.randint(50, 130),
        }
        data_b64 = base64.b64encode(json.dumps(env, separators=(",", ":")).encode("utf-8")).decode("ascii")
        return json.dumps(
            {
                "appId": "default",
                "organization": cls._SM_ORGANIZATION,
                "ep": ep,
                "data": data_b64,
                "os": "web",
                "encode": 1,
                "compress": 0,
            },
            separators=(",", ":"),
        )

    def _fetch_market_device_id(self) -> str:
        headers = {
            "User-Agent": self.MARKET_USER_AGENT,
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": self.MARKET_BASE_URL,
            "Referer": f"{self.MARKET_BASE_URL}/portal/mobilecloud/index.html?path=newsignin",
        }
        try:
            payload_str = self._generate_market_device_profile()
            self._throttle_request()
            resp = self._market_session.post(
                "https://slw.h5cmpassport.com:9090/deviceprofile/v4",
                data=payload_str,
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            device_id = str(((data or {}).get("detail") or {}).get("deviceId") or "")
            if str((data or {}).get("code") or "") == "1100" and device_id:
                return device_id if device_id.startswith("B") else f"B{device_id}"
        except Exception as exc:
            self._debug_log_json("signin.device_id_failed", {"message": str(exc)})
        return ""

    def _load_market_device_id(self) -> str:
        if self._market_device_id:
            return self._market_device_id
        self._market_device_id = self._fetch_market_device_id()
        if not self._market_device_id:
            fallback = hashlib.md5(f"{self._username or self._phone or self._account_name}:{self._current_millis()}".encode("utf-8")).hexdigest()
            self._market_device_id = f"B{fallback}"
        return self._market_device_id

    def _get_market_device_id(self) -> str:
        device_id = self._load_market_device_id()
        return device_id if device_id.startswith("B") else f"B{device_id}"

    def _seed_market_device_cookie(self) -> None:
        device_id = self._get_market_device_id()
        if not device_id:
            return
        cookie_value = device_id[1:] if device_id.startswith("B") else device_id
        cookie_name = f".thumbcache_{self._username or self._phone or self.index}"
        self._market_session.cookies.set(cookie_name, cookie_value, domain="m.mcloud.139.com", path="/")

    def _build_market_page_url(self, source_id: str | None = None) -> str:
        current_source_id = source_id or self.MARKET_SOURCE_ID
        return (
            f"{self.MARKET_BASE_URL}/portal/mobilecloud/index.html?path=newsignin"
            f"&sourceid={current_source_id}&enableShare=1&token={quote(self._market_sso_token or '', safe='')}&targetSourceId=001005"
        )

    def _build_market_context(self, jwt_token: str, sso_token: str = "") -> None:
        if sso_token:
            self._market_sso_token = sso_token
        self._market_jwt_token = jwt_token
        user_domain_id = self._extract_user_domain_id(jwt_token)
        if user_domain_id:
            self._user_domain_id = user_domain_id
        self._market_session_prepared = False
        self._seed_market_device_cookie()

    def _post_signin_journaling(self, keyword: str, source_id: str | None = None) -> bool:
        current_source_id = source_id or self.MARKET_SOURCE_ID
        payload = f"module=uservisit&optkeyword={keyword}&sourceid={current_source_id}&marketName={self.SIGNIN_ACTIVITY_ID}"
        try:
            self._request_text(
                "POST",
                f"{self.MARKET_BASE_URL}/ycloud/visitlog/journaling",
                headers={
                    **self._market_headers(include_jwt=True, jwt_token=self._market_jwt_token),
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "Referer": self._build_market_page_url(current_source_id),
                },
                data=payload,
                cookies=self._market_cookies(self._market_jwt_token),
                timeout=15,
                session=self._market_session,
            )
            return True
        except Exception:
            return False

    def _build_receive_headers(self, jwt_token: str, source_id: str | None = None) -> dict[str, str]:
        current_source_id = source_id or self.MARKET_SOURCE_ID
        return {
            **self._market_headers(include_jwt=True, jwt_token=jwt_token),
            "showLoading": "true",
            "appVersion": "13.0.0.0",
            "activityId": self.SIGNIN_ACTIVITY_ID,
            "Referer": self._build_market_page_url(current_source_id),
        }

    def _prepare_signin_center_session(self, *, for_receive: bool = False, source_id: str | None = None) -> None:
        if not self._market_jwt_token:
            return
        current_source_id = source_id or self.MARKET_SOURCE_ID
        if not self._market_session_prepared:
            page_url = self._build_market_page_url(current_source_id)
            try:
                self._request_text(
                    "GET",
                    page_url,
                    headers={
                        **self._market_headers(include_jwt=True, jwt_token=self._market_jwt_token),
                        "Referer": page_url,
                    },
                    cookies=self._market_cookies(self._market_jwt_token),
                    timeout=20,
                    session=self._market_session,
                )
            except Exception:
                pass
            for keyword in (
                "newsignin_index_pv",
                "newsignin_index_client",
                "newsignin_index_app_client",
                "newsignin_index_cookie_login",
                "newsignin_index_cookie",
                "newsignin_index_app_cookie_login",
            ):
                self._post_signin_journaling(keyword, current_source_id)
            self._market_session_prepared = True
        if for_receive:
            self._post_signin_journaling("newsignin_index_receive_type", current_source_id)

    def _get_today_sign_state(self, result: Any) -> bool | None:
        if not isinstance(result, dict):
            return None
        today_sign_in = result.get("todaySignIn")
        if isinstance(today_sign_in, bool):
            return today_sign_in
        for day in result.get("cal") or []:
            if day.get("t"):
                return bool(day.get("s"))
        return None

    def _extract_signin_reward(self, payload: Any) -> int:
        if isinstance(payload, dict):
            for key in ("cloudCount", "reward", "count", "total", "receive"):
                value = payload.get(key)
                try:
                    return int(value) if value is not None else 0
                except Exception:
                    continue
            for value in payload.values():
                reward = self._extract_signin_reward(value)
                if reward:
                    return reward
        elif isinstance(payload, list):
            for item in payload:
                reward = self._extract_signin_reward(item)
                if reward:
                    return reward
        return 0

    def _query_market_sso_token(self, to_source_id: str = "001005") -> str:
        account = self._username or self._phone or self._parse_phone_from_authorization(self._authorization)
        if not account:
            raise RuntimeError("缺少账号信息，无法获取签到 ssoToken")
        headers = {
            "Authorization": self._normalize_basic_auth(self._authorization),
            "User-Agent": self.MARKET_USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Host": "orches.yun.139.com",
        }
        payload = self._market_request_json(
            "POST",
            "https://orches.yun.139.com/orchestration/auth-rebuild/token/v1.0/querySpecToken",
            headers=headers,
            json_body={"account": account, "toSourceId": to_source_id},
            timeout=20,
        )
        if not isinstance(payload, dict) or not bool(payload.get("success")):
            raise RuntimeError(str((payload or {}).get("message") or "获取签到 ssoToken 失败"))
        token = str(((payload.get("data") or {}).get("token")) or "")
        if not token:
            raise RuntimeError("签到 ssoToken 为空")
        return token

    def _query_market_jwt_token(self, sso_token: str) -> str:
        payload = self._market_request_json(
            "POST",
            "https://caiyun.feixin.10086.cn/portal/auth/tyrzLogin.action",
            headers=self._market_headers(),
            params={"ssoToken": sso_token},
            timeout=20,
        )
        code = -1
        if isinstance(payload, dict):
            try:
                code = int(payload.get("code", -1))
            except Exception:
                code = -1
        if not isinstance(payload, dict) or code != 0:
            raise RuntimeError(str((payload or {}).get("msg") or "获取签到 jwtToken 失败"))
        token = str(((payload.get("result") or {}).get("token")) or "")
        if not token:
            raise RuntimeError("签到 jwtToken 为空")
        return token

    def _query_market_signin_info(self, jwt_token: str) -> dict[str, Any]:
        self._build_market_context(jwt_token)
        self._prepare_signin_center_session()
        payload = self._market_request_json(
            "GET",
            f"{self.MARKET_BASE_URL}/ycloud/signin/page/infoV3",
            headers=self._market_headers(include_jwt=True, jwt_token=jwt_token),
            params={"client": "app"},
            cookies=self._market_cookies(jwt_token),
            timeout=20,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("查询签到状态失败")
        return payload

    def _do_market_signin(self, jwt_token: str) -> dict[str, Any]:
        self._build_market_context(jwt_token)
        self._prepare_signin_center_session()
        payload = self._market_request_json(
            "GET",
            f"{self.MARKET_BASE_URL}/ycloud/signin/page/startSignIn",
            headers=self._market_headers(include_jwt=True, jwt_token=jwt_token),
            params={"client": "app"},
            cookies=self._market_cookies(jwt_token),
            timeout=20,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("签到失败")
        return payload

    def _build_sign_stage_result(self, *, ok: bool, message: str, reward: int = 0, skipped: bool = False, raw: Any = None, **extra: Any) -> dict[str, Any]:
        result = {
            "ok": ok,
            "message": message,
            "reward": reward,
            "skipped": skipped,
            "raw": raw,
        }
        result.update(extra)
        return result

    def _skip_sign_stage(self, message: str) -> dict[str, Any]:
        return self._build_sign_stage_result(ok=False, skipped=True, message=message)

    def _start_sign_in_budget(self) -> None:
        self._sign_in_deadline_ts = time.monotonic() + self.SIGN_IN_TOTAL_BUDGET_SECONDS

    def _clear_sign_in_budget(self) -> None:
        self._sign_in_deadline_ts = None

    def _remaining_sign_in_seconds(self) -> float | None:
        if self._sign_in_deadline_ts is None:
            return None
        return max(self._sign_in_deadline_ts - time.monotonic(), 0.0)

    def _effective_timeout(self, requested_timeout: float) -> float:
        remaining = self._remaining_sign_in_seconds()
        if remaining is None:
            return requested_timeout
        if remaining <= 0:
            raise TimeoutError("签到执行超时，已停止后续请求")
        return max(min(requested_timeout, remaining), 0.2)

    def _sleep_with_budget(self, seconds: float) -> None:
        remaining = self._remaining_sign_in_seconds()
        if remaining is None:
            time.sleep(seconds)
            return
        if remaining <= 0:
            raise TimeoutError("签到执行超时，已停止后续等待")
        time.sleep(min(seconds, max(remaining - 0.1, 0)))

    def _run_sign_stage(self, runner: Any, name: str, *, required_jwt: bool = False, jwt_token: str = "") -> dict[str, Any]:
        if required_jwt and not jwt_token:
            return self._skip_sign_stage("缺少签到上下文，已跳过")
        remaining = self._remaining_sign_in_seconds()
        if remaining is not None and remaining < self.SIGN_IN_STAGE_MIN_SECONDS:
            return self._skip_sign_stage(f"签到剩余预算不足 {self.SIGN_IN_STAGE_MIN_SECONDS:.1f}s，已跳过")
        try:
            result = runner(jwt_token) if required_jwt else runner()
        except Exception as exc:
            self._debug_log_json(f"signin.stage_failed.{name}", {"message": str(exc)})
            return self._build_sign_stage_result(ok=False, message=str(exc))
        if isinstance(result, dict):
            return result
        return self._build_sign_stage_result(ok=True, message="执行完成", raw=result)

    def _prepare_market_context(self) -> dict[str, str]:
        sso_token = self._query_market_sso_token()
        jwt_token = self._query_market_jwt_token(sso_token)
        self._build_market_context(jwt_token, sso_token)
        return {"sso_token": sso_token, "jwt_token": jwt_token}

    def _jwt_activity_headers(self, jwt_token: str) -> dict[str, str]:
        headers = {
            "User-Agent": self.MARKET_USER_AGENT,
            "Accept": "*/*",
            "Host": "caiyun.feixin.10086.cn:7071",
        }
        if jwt_token:
            headers["jwtToken"] = jwt_token
        return headers

    def _jwt_activity_cookies(self, jwt_token: str) -> dict[str, str]:
        cookies = {"sensors_stay_time": str(self._current_millis())}
        if jwt_token:
            cookies["jwtToken"] = jwt_token
        return cookies

    def _sign_in_market_stage(self, jwt_token: str) -> dict[str, Any]:
        status_data = self._query_market_signin_info(jwt_token)
        raw: dict[str, Any] = {"status": status_data}
        if int(status_data.get("code", -1)) != 0:
            raise RuntimeError(str(status_data.get("msg") or "查询签到状态失败"))
        result = status_data.get("result") or {}
        if bool(self._get_today_sign_state(result)):
            reward = self._extract_signin_reward(result)
            return self._build_sign_stage_result(ok=True, message="今日已签到", reward=reward, raw=raw)
        signin_data = self._do_market_signin(jwt_token)
        raw["signin"] = signin_data
        sign_result = signin_data.get("result") or {}
        if int(signin_data.get("code", -1)) == 0 and bool(self._get_today_sign_state(sign_result)):
            reward = self._extract_signin_reward(sign_result)
            return self._build_sign_stage_result(ok=True, message=f"签到成功，获得 {reward} 云朵" if reward else "签到成功", reward=reward, raw=raw)
        latest_data = self._query_market_signin_info(jwt_token)
        raw["latest"] = latest_data
        latest_result = latest_data.get("result") or {}
        if int(latest_data.get("code", -1)) == 0 and bool(self._get_today_sign_state(latest_result)):
            reward = self._extract_signin_reward(latest_result) or self._extract_signin_reward(sign_result)
            return self._build_sign_stage_result(ok=True, message=f"签到成功，获得 {reward} 云朵" if reward else "签到成功", reward=reward, raw=raw)
        if int(signin_data.get("code", -1)) != 0:
            raise RuntimeError(str(signin_data.get("msg") or "签到失败"))
        reward = self._extract_signin_reward(sign_result or signin_data)
        return self._build_sign_stage_result(ok=True, message=f"签到成功，获得 {reward} 云朵" if reward else "签到成功", reward=reward, raw=raw)

    def _click_market_task(self, task_id: int | str, key: str = "task") -> dict[str, Any]:
        payload = self._market_request_json(
            "GET",
            f"{self.MARKET_BASE_URL}/ycloud/signin/task/click",
            headers=self._market_headers(include_jwt=True, jwt_token=self._market_jwt_token),
            params={"key": key, "id": task_id},
            cookies=self._market_cookies(self._market_jwt_token),
            timeout=20,
        )
        return payload if isinstance(payload, dict) else {}

    def _run_market_click_stage(self, _jwt_token: str) -> dict[str, Any]:
        rewards: list[str] = []
        success = 0
        for _ in range(15):
            remaining = self._remaining_sign_in_seconds()
            if remaining is not None and remaining < 1.0:
                break
            data = self._click_market_task(319) or {}
            result = data.get("result") or {}
            if result:
                success += 1
                text = str(result)
                if text:
                    rewards.append(text)
            self._sleep_with_budget(0.2)
        if success:
            return self._build_sign_stage_result(ok=True, message=f"戳一戳完成 {success} 次", raw={"rewards": rewards[:5], "count": success})
        return self._build_sign_stage_result(ok=False, message="戳一戳未获得奖励")

    def _build_cloud_file_headers(self) -> dict[str, str]:
        return {
            "x-yun-op-type": "1",
            "x-yun-sub-op-type": "100",
            "x-yun-api-version": "v1",
            "x-yun-client-info": "6|127.0.0.1|1|12.1.0|realme|RMX5060|BCFF2BBA6881DD8E4971803C63DDB5E4|02-00-00-00-00-00|android 15|1264X2592|zh||||032|0|",
            "x-yun-app-channel": "10000023",
            "Authorization": self._normalize_basic_auth(self._authorization),
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "okhttp/4.12.0",
            "Host": "personal-kd-njs.yun.139.com",
            "Connection": "Keep-Alive",
        }

    def _build_share_headers(self) -> dict[str, str]:
        return {
            "Authorization": self._normalize_basic_auth(self._authorization),
            "x-yun-api-version": "v1",
            "x-yun-app-channel": "10000023",
            "x-yun-client-info": "||9|13.0.0|Chrome|143.0.7499.146|codextestshare||Windows 10||zh-CN|||Q2hyb21l||",
            "x-yun-module-type": "100",
            "x-yun-svc-type": "1",
            "x-SvcType": "1",
            "x-yun-channel-source": "10000023",
            "x-huawei-channelSrc": "10000023",
            "Content-Type": "application/json;charset=UTF-8",
            "CMS-DEVICE": "default",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
            "Referer": "https://yun.139.com/shareweb/",
            "Origin": "https://yun.139.com",
        }

    def _create_cloud_file(self, prefix: str) -> dict[str, Any] | None:
        now = datetime.now(timezone(timedelta(hours=8)))
        file_size = len(self.CLOUD_FILE_DUMMY_CONTENT)
        file_name = f"{prefix}{now.strftime('%Y%m%d_%H%M%S')}.txt"
        payload = {
            "contentHash": self.CLOUD_FILE_DUMMY_HASH,
            "contentHashAlgorithm": "SHA256",
            "contentType": "application/oct-stream",
            "fileRenameMode": "force_rename",
            "localCreatedAt": now.isoformat(timespec="milliseconds"),
            "name": file_name,
            "parallelUpload": True,
            "parentFileId": "/",
            "partInfos": [{"end": file_size, "partNumber": 1, "partSize": file_size, "start": 0}],
            "size": file_size,
            "type": "file",
        }
        data = self._request_json(
            "POST",
            f"{self.PERSONAL_KD_NJS_URL}/hcy/file/create",
            headers=self._build_cloud_file_headers(),
            json_body=payload,
            timeout=30,
        )
        if not isinstance(data, dict) or not bool(data.get("success")):
            return None
        payload_data = data.get("data") or {}
        return {"fileId": payload_data.get("fileId"), "fileName": payload_data.get("fileName") or file_name}

    def _list_cloud_root_files(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_cursor = ""
        while True:
            response = self._request_json(
                "POST",
                f"{self.PERSONAL_KD_NJS_URL}/hcy/file/list",
                headers=self._build_cloud_file_headers(),
                json_body={
                    "imageThumbnailStyleList": ["Small", "Large"],
                    "orderBy": "updated_at",
                    "orderDirection": "DESC",
                    "pageInfo": {"pageCursor": page_cursor, "pageSize": 100},
                    "parentFileId": "/",
                },
                timeout=30,
            )
            if not isinstance(response, dict) or not bool(response.get("success")):
                return items
            data = response.get("data") or {}
            items.extend(data.get("items") or [])
            page_cursor = str(data.get("nextPageCursor") or "")
            if not page_cursor:
                return items

    def _is_cleanup_upload_file(self, item: dict[str, Any]) -> bool:
        if item.get("type") != "file" or item.get("parentFileId") != "/":
            return False
        name = str(item.get("name") or "")
        if not (name.endswith(".txt") and (name.startswith("auto_upload_") or name.startswith("auto_share_"))):
            return False
        size = item.get("size")
        content_hash = item.get("contentHash")
        return size in (0, 1, None) or content_hash == self.CLOUD_FILE_DUMMY_HASH

    def _trash_cloud_files(self, file_ids: list[str]) -> bool:
        if not file_ids:
            return True
        response = self._request_json(
            "POST",
            f"{self.PERSONAL_KD_NJS_URL}/hcy/recyclebin/batchTrash",
            headers=self._build_cloud_file_headers(),
            json_body={"fileIds": file_ids},
            timeout=30,
        )
        return isinstance(response, dict) and bool(response.get("success"))

    def _cleanup_uploaded_files(self, current_file: dict[str, Any] | None = None) -> bool:
        file_ids: list[str] = []
        if current_file and current_file.get("fileId"):
            file_ids.append(str(current_file["fileId"]))
        for item in self._list_cloud_root_files():
            if self._is_cleanup_upload_file(item):
                file_ids.append(str(item.get("fileId") or ""))
        unique = [item for item in dict.fromkeys(file_ids) if item]
        if not unique:
            return True
        return self._trash_cloud_files(unique)

    def _upload_dummy_file(self) -> dict[str, Any] | None:
        created = self._create_cloud_file("auto_upload_")
        if created:
            self._cleanup_uploaded_files(created)
        return created

    def _complete_share_file_task(self, task: dict[str, Any]) -> dict[str, Any] | None:
        share_file = self._create_cloud_file("auto_share_")
        if not share_file:
            return None
        try:
            response = self._request_json(
                "POST",
                f"{self.BASE_URL}/orchestration/personalCloud-rebuild/outlink/v1.0/getOutLink",
                headers=self._build_share_headers(),
                json_body={
                    "getOutLinkReq": {
                        "subLinkType": 0,
                        "encrypt": 0,
                        "coIDLst": [share_file.get("fileId")],
                        "caIDLst": [],
                        "pubType": 1,
                        "dedicatedName": share_file.get("fileName", ""),
                        "periodUnit": 1,
                        "viewerLst": [],
                        "extInfo": {"isWatermark": 0, "shareChannel": "3001"},
                        "commonAccountInfo": self._account_payload(),
                    }
                },
                timeout=30,
            )
        finally:
            self._trash_cloud_files([str(share_file.get("fileId") or "")])
        result = ((response or {}).get("data") or {}).get("result") or {}
        if not isinstance(response, dict) or not bool(response.get("success")) or str(result.get("resultCode") or "") != "0":
            return None
        return self._query_cloud_task(int(task.get("id") or 434), "month") or task

    def _build_ai_headers(self, *, use_client_info: bool = False) -> dict[str, str]:
        headers = {
            "Connection": "keep-alive",
            "sec-ch-ua-platform": '"Android"',
            "Authorization": self._normalize_basic_auth(self._authorization),
            "x-yun-api-version": "v1",
            "x-yun-tid": str(uuid.uuid4()),
            "sec-ch-ua": '"Android WebView";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
            "sec-ch-ua-mobile": "?1",
            "X-Requested-With": "com.chinamobile.mcloud",
            "Origin": "https://frontend.mcloud.139.com",
            "Referer": "https://frontend.mcloud.139.com/",
            "User-Agent": f"Mozilla/5.0 (Linux; Android 10; MI 8 Build/QKQ1.190828.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/143.0.7499.146 Mobile Safari/537.36 MCloudApp/13.0.0 tid/{uuid.uuid4()}",
            "Content-Type": "application/json",
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "zh,zh-CN;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        if use_client_info:
            headers["Accept"] = "text/event-stream"
            headers["x-yun-client-info"] = f"4||1|13.0.0||MI 8|{uuid.uuid4().hex.upper()}||android 10|||||"
            headers["x-yun-app-channel"] = "101"
        else:
            headers["Accept"] = "*/*"
            headers["x-DeviceInfo"] = f"||36|13.0.0||MI 8|{uuid.uuid4()}||android 10|||||"
        return headers

    def _get_ai_camera_sample_base64(self) -> str:
        return f"data:image/jpg;base64,{self.AI_CAMERA_SAMPLE_BASE64}"

    @staticmethod
    def _is_ai_chat_success(text: str) -> bool:
        payloads = []
        for line in (text or "").splitlines():
            if line.startswith("data:"):
                payloads.append(line[5:].strip())
        if not payloads and text:
            payloads.append(text.strip())
        for payload in payloads:
            if not payload or payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if data.get("success") or data.get("code") == "0000":
                return True
        return False

    def _complete_ai_camera_task(self) -> bool:
        if not self._user_domain_id:
            return False
        recognize_data = self._request_json(
            "POST",
            "https://ai.yun.139.com/api/image/aiRecognize",
            headers=self._build_ai_headers(),
            data=json.dumps(
                {
                    "channelId": "101",
                    "userId": self._user_domain_id,
                    "recognizeType": "1",
                    "base64": self._get_ai_camera_sample_base64(),
                    "sendType": "2",
                    "imageExt": "jpg",
                    "uploadToCloud": True,
                    "timeout": 30000,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            timeout=30,
        )
        if not isinstance(recognize_data, dict) or not bool(recognize_data.get("success")):
            return False
        result = recognize_data.get("data") or {}
        file_id = str(result.get("fileId") or "")
        task_id = str(result.get("taskId") or int(time.time() * 1000))
        if not file_id:
            return False
        file_name = f"{int(task_id) + 1}.jpeg" if task_id.isdigit() else f"{task_id}.jpeg"
        chat_payload = json.dumps(
            {
                "userId": self._user_domain_id,
                "sessionId": "",
                "applicationType": "chat",
                "applicationId": "",
                "sourceChannel": "101",
                "dialogueInput": {
                    "dialogue": "？",
                    "prompt": "",
                    "inputTime": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="milliseconds"),
                    "enableForceLlm": False,
                    "enableForceNetworkSearch": True,
                    "enableModelThinking": False,
                    "enableAllNetworkSearch": False,
                    "enableKnowledgeAndNetworkSearch": False,
                    "enableRegenerate": False,
                    "versionInfo": {"h5Version": "2.7.6"},
                    "extInfo": "{}",
                    "sortInfo": {},
                    "toolSetting": {"imageToolSetting": {"enableLlmDescribe": True}},
                    "attachment": {"attachmentTypeList": [3], "fileList": [{"fileId": file_id, "name": file_name}]},
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        response_text = self._request_text(
            "POST",
            "https://ai.yun.139.com/api/outer/assistant/chat/v2/add",
            headers=self._build_ai_headers(use_client_info=True),
            data=chat_payload,
            timeout=30,
        )
        return self._is_ai_chat_success(response_text)

    @staticmethod
    def _get_task_progress(task: dict[str, Any]) -> str:
        progress_parts = []
        currstep = task.get("currstep", 0)
        process = task.get("process", 0)
        if currstep:
            progress_parts.append(f"阶段{currstep}")
        if process:
            progress_parts.append(f"进度{process}")
        return f" ({'，'.join(progress_parts)})" if progress_parts else ""

    @staticmethod
    def _strip_task_name(task: dict[str, Any]) -> str:
        return re.sub(r"<[^>]+>", "", str(task.get("name") or ""))

    @staticmethod
    def _get_task_step_types(task: dict[str, Any]) -> set[str]:
        return set(task.get("stepTypeSet") or [])

    def _get_task_click_keys(self, task: dict[str, Any]) -> list[str]:
        task_id = int(task.get("id") or 0)
        currstep = int(task.get("currstep") or 0)
        step_types = self._get_task_step_types(task)
        if task_id == 409:
            return ["task2"] if currstep > 0 else ["task", "task2"]
        if "click" in step_types:
            return ["task"]
        if task.get("state", "") != "FINISH":
            return ["task"]
        return []

    def _query_cloud_task(self, task_id: int, group: str = "time") -> dict[str, Any] | None:
        data = self._market_request_json(
            "POST",
            f"{self.MARKET_BASE_URL}/ycloud/signin/task/taskListV2",
            headers=self._market_headers(include_jwt=True, jwt_token=self._market_jwt_token),
            json_body={"marketname": self.SIGNIN_ACTIVITY_ID, "clientVersion": "13.0.0", "group": group},
            cookies=self._market_cookies(self._market_jwt_token),
            timeout=20,
        )
        if not isinstance(data, dict) or int(data.get("code", -1)) != 0:
            return None
        for task in ((data.get("result") or {}).get(group) or []):
            if int(task.get("id") or 0) == int(task_id):
                return task
        return None

    def _complete_monthly_upload_task(self, task: dict[str, Any]) -> bool:
        target_count = 100
        current_process = int(task.get("process") or 0)
        for _ in range(3):
            remaining = self._remaining_sign_in_seconds()
            if remaining is not None and remaining < 4.0:
                return False
            remaining = max(0, target_count - current_process)
            if remaining == 0:
                return True
            for _ in range(remaining):
                time_left = self._remaining_sign_in_seconds()
                if time_left is not None and time_left < 2.0:
                    return False
                self._upload_dummy_file()
            refreshed = self._query_cloud_task(int(task.get("id") or 522), "time")
            if not refreshed:
                return False
            refreshed_process = int(refreshed.get("process") or 0)
            if refreshed.get("state") == "FINISH" or refreshed_process >= target_count:
                return True
            if refreshed_process <= current_process:
                return False
            current_process = refreshed_process
        return False

    def _format_notice_task_log(self, task_name: str, notice_status: dict[str, Any]) -> str:
        if not notice_status:
            return f"需手动完成: {task_name}"
        push_on = int(notice_status.get("pushOn") or 0)
        first_status = int(notice_status.get("firstTaskStatus") or 0)
        second_status = int(notice_status.get("secondTaskStatus") or 0)
        on_duration = int(notice_status.get("onDuaration") or 0)
        total = int(notice_status.get("total") or 31)
        if push_on != 1:
            return f"需手动完成: {task_name} (通知未开启)"
        if second_status == 3:
            return f"已完成: {task_name}"
        if first_status != 3:
            return f"待领取: {task_name} (首日奖励可领取)"
        if second_status == 2:
            return f"待领取: {task_name} (已开启{on_duration}/{total}天)"
        return f"进行中: {task_name} (已开启{on_duration}/{total}天)"

    def _get_notice_status(self) -> dict[str, Any]:
        data = self._request_json("GET", "https://caiyun.feixin.10086.cn/market/msgPushOn/task/status", headers=self._market_headers(include_jwt=True, jwt_token=self._market_jwt_token), cookies=self._market_cookies(self._market_jwt_token), timeout=20)
        if not isinstance(data, dict) or int(data.get("code", -1)) != 0:
            return {}
        return data.get("result") or {}

    def _claim_revival_reward(self) -> dict[str, Any]:
        data = self._market_request_json(
            "POST",
            f"{self.MARKET_BASE_URL}/ycloud/signin/page/receiveRevivalReward",
            headers=self._market_headers(include_jwt=True, jwt_token=self._market_jwt_token),
            json_body={},
            cookies=self._market_cookies(self._market_jwt_token),
            timeout=20,
        )
        if not isinstance(data, dict):
            return {"message": "复活卡接口无响应"}
        result = data.get("result") or {}
        reward = int(result.get("rewardClouds") or 0)
        return {"code": data.get("code"), "reward": reward, "total": result.get("totalClouds"), "message": str(data.get("msg") or "")}

    def _claim_multiple_clouds(self) -> dict[str, Any]:
        data = self._market_request_json(
            "GET",
            f"{self.MARKET_BASE_URL}/ycloud/signin/page/multiple",
            headers=self._market_headers(include_jwt=True, jwt_token=self._market_jwt_token),
            cookies=self._market_cookies(self._market_jwt_token),
            timeout=20,
        )
        if not isinstance(data, dict):
            return {}
        result = data.get("result") or {}
        return {"code": data.get("code"), "cloudCount": int(result.get("cloudCount") or 0)}

    def _handle_cloud_v2_task(self, group: str, task: dict[str, Any]) -> dict[str, Any]:
        task_id = int(task.get("id") or 0)
        task_name = self._strip_task_name(task)
        task_status = str(task.get("state") or "")
        if task_status == "FINISH":
            return {"task_id": task_id, "task_name": task_name, "status": "finished"}
        if group == "day" and task_id == 106:
            self._upload_dummy_file()
            return {"task_id": task_id, "task_name": task_name, "status": "attempted"}
        if task_id == 522:
            if self._complete_monthly_upload_task(task):
                return {"task_id": task_id, "task_name": task_name, "status": "finished"}
            return {"task_id": task_id, "task_name": task_name, "status": "manual", "message": self._get_task_progress(task)}
        if task_id == 434:
            refreshed = self._complete_share_file_task(task)
            if refreshed and refreshed.get("state") == "FINISH":
                return {"task_id": task_id, "task_name": task_name, "status": "finished"}
            return {"task_id": task_id, "task_name": task_name, "status": "manual", "message": self._get_task_progress(refreshed or task)}
        if task_id == 406:
            return {"task_id": task_id, "task_name": task_name, "status": "info", "message": self._format_notice_task_log(task_name, self._get_notice_status())}
        if task_id == 478:
            click_data = self._click_market_task(task_id, "randomCloudTask") or {}
            if int(click_data.get("code", -1)) == 0:
                return {"task_id": task_id, "task_name": task_name, "status": "finished", "raw": click_data}
            return {"task_id": task_id, "task_name": task_name, "status": "manual", "message": str(click_data.get("msg") or "未知错误")}
        task_keys = self._get_task_click_keys(task)
        if task_keys:
            for task_key in task_keys:
                click_data = self._click_market_task(task_id, task_key)
                if int((click_data or {}).get("code", -1)) != 0:
                    return {"task_id": task_id, "task_name": task_name, "status": "failed", "message": str((click_data or {}).get("msg") or "任务登记失败")}
            if task_id == 585 and self._complete_ai_camera_task():
                return {"task_id": task_id, "task_name": task_name, "status": "finished"}
            return {"task_id": task_id, "task_name": task_name, "status": "registered"}
        return {"task_id": task_id, "task_name": task_name, "status": "manual", "message": self._get_task_progress(task)}

    def _run_cloud_tasks_stage(self, jwt_token: str) -> dict[str, Any]:
        groups = [("cloudEmail", "联动任务"), ("time", "新版热门任务"), ("day", "云盘每日任务"), ("month", "云盘每月任务")]
        handled: list[dict[str, Any]] = []
        failures = 0
        for group, _title in groups:
            data = self._market_request_json(
                "POST",
                f"{self.MARKET_BASE_URL}/ycloud/signin/task/taskListV2",
                headers=self._market_headers(include_jwt=True, jwt_token=jwt_token),
                json_body={"marketname": self.SIGNIN_ACTIVITY_ID, "clientVersion": "13.0.0", "group": group},
                cookies=self._market_cookies(jwt_token),
                timeout=20,
            )
            if not isinstance(data, dict) or int(data.get("code", -1)) != 0:
                failures += 1
                handled.append({"group": group, "status": "failed", "message": str((data or {}).get("msg") or "获取任务列表失败")})
                continue
            for task in ((data.get("result") or {}).get(group) or []):
                handled.append({"group": group, **self._handle_cloud_v2_task(group, task)})
        revival = self._claim_revival_reward()
        multiple = self._claim_multiple_clouds()
        self._cleanup_uploaded_files()
        return self._build_sign_stage_result(
            ok=failures == 0,
            message="云朵中心任务处理完成" if failures == 0 else f"云朵中心任务处理完成，{failures} 个分组获取失败",
            raw={"tasks": handled, "revival": revival, "multiple": multiple},
            finished=sum(1 for item in handled if item.get("status") in {"finished", "registered", "attempted"}),
        )

    def _query_legacy_market_task_list(self, jwt_token: str, market_name: str) -> dict[str, Any]:
        data = self._request_json(
            "GET",
            "https://caiyun.feixin.10086.cn/market/signin/task/taskList",
            headers=self._market_headers(include_jwt=True, jwt_token=jwt_token),
            params={"marketname": market_name},
            cookies=self._market_cookies(jwt_token),
            timeout=20,
        )
        return data if isinstance(data, dict) else {}

    def _click_legacy_market_task(self, jwt_token: str, task_id: int | str, key: str = "task") -> dict[str, Any]:
        data = self._request_json(
            "GET",
            "https://caiyun.feixin.10086.cn/market/signin/task/click",
            headers=self._market_headers(include_jwt=True, jwt_token=jwt_token),
            params={"key": key, "id": task_id},
            cookies=self._market_cookies(jwt_token),
            timeout=20,
        )
        return data if isinstance(data, dict) else {}

    def _run_cloud_game_stage(self, jwt_token: str) -> dict[str, Any]:
        info = self._request_json(
            "GET",
            "https://caiyun.feixin.10086.cn/market/signin/hecheng1T/info",
            headers=self._market_headers(include_jwt=True, jwt_token=jwt_token),
            params={"op": "info"},
            cookies=self._market_cookies(jwt_token),
            timeout=20,
        )
        raw: dict[str, Any] = {"info": info, "attempts": []}
        if not isinstance(info, dict) or int(info.get("code", -1)) != 0:
            return self._build_sign_stage_result(ok=False, message=str((info or {}).get("msg") or "获取云朵大作战信息失败"), raw=raw)
        currnum = int((((info.get("result") or {}).get("info") or {}).get("curr")) or 0)
        if currnum <= 0:
            return self._build_sign_stage_result(ok=True, message="云朵大作战今日无可用次数", raw=raw)
        attempts = min(currnum, 2)
        success = 0
        for _ in range(attempts):
            begin_data = self._request_json(
                "GET",
                "https://caiyun.feixin.10086.cn/market/signin/hecheng1T/beinvite",
                headers=self._market_headers(include_jwt=True, jwt_token=jwt_token),
                cookies=self._market_cookies(jwt_token),
                timeout=20,
            )
            attempt_raw: dict[str, Any] = {"begin": begin_data}
            self._sleep_with_budget(float(random.randint(10, 12)))
            finish_data = self._request_json(
                "GET",
                "https://caiyun.feixin.10086.cn/market/signin/hecheng1T/finish",
                headers=self._market_headers(include_jwt=True, jwt_token=jwt_token),
                params={"flag": "true"},
                cookies=self._market_cookies(jwt_token),
                timeout=20,
            )
            attempt_raw["finish"] = finish_data
            raw["attempts"].append(attempt_raw)
            if isinstance(finish_data, dict) and int(finish_data.get("code", -1)) == 0:
                success += 1
        message = f"云朵大作战完成 {success}/{attempts} 次"
        if currnum > attempts:
            message = f"{message}，剩余 {currnum - attempts} 次未执行"
        return self._build_sign_stage_result(ok=success > 0, message=message, raw=raw, finished=success)

    def _claim_notice_reward(self, jwt_token: str, reward_type: int) -> dict[str, Any]:
        data = self._request_json(
            "POST",
            "https://caiyun.feixin.10086.cn/market/msgPushOn/task/obtain",
            headers=self._market_headers(include_jwt=True, jwt_token=jwt_token),
            json_body={"type": reward_type},
            cookies=self._market_cookies(jwt_token),
            timeout=20,
        )
        return data if isinstance(data, dict) else {}

    def _run_notice_stage(self, jwt_token: str) -> dict[str, Any]:
        status_data = self._request_json(
            "GET",
            "https://caiyun.feixin.10086.cn/market/msgPushOn/task/status",
            headers=self._market_headers(include_jwt=True, jwt_token=jwt_token),
            cookies=self._market_cookies(jwt_token),
            timeout=20,
        )
        raw: dict[str, Any] = {"status": status_data, "claims": []}
        if not isinstance(status_data, dict) or int(status_data.get("code", -1)) != 0:
            return self._build_sign_stage_result(ok=False, message=str((status_data or {}).get("msg") or "查询通知任务失败"), raw=raw)
        result = status_data.get("result") or {}
        push_on = int(result.get("pushOn") or 0)
        first_status = int(result.get("firstTaskStatus") or 0)
        second_status = int(result.get("secondTaskStatus") or 0)
        on_duration = int(result.get("onDuaration") or 0)
        if push_on != 1:
            return self._build_sign_stage_result(ok=True, message="通知云朵未开启，需手动完成", raw=raw, manual=True)
        claimed = 0
        if first_status in (1, 2):
            reward_data = self._claim_notice_reward(jwt_token, 1)
            raw["claims"].append({"type": 1, "data": reward_data})
            if int((reward_data or {}).get("code", -1)) == 0:
                claimed += 1
        if second_status == 2:
            reward_data = self._claim_notice_reward(jwt_token, 2)
            raw["claims"].append({"type": 2, "data": reward_data})
            if int((reward_data or {}).get("code", -1)) == 0:
                claimed += 1
        message = f"通知云朵状态正常，已开启 {on_duration} 天"
        if claimed:
            message = f"{message}，领取奖励 {claimed} 次"
        return self._build_sign_stage_result(ok=True, message=message, raw=raw, finished=claimed)

    def _run_mail_tasks_stage(self, jwt_token: str) -> dict[str, Any]:
        task_data = self._query_legacy_market_task_list(jwt_token, self.MAIL_SIGNIN_ACTIVITY_ID)
        raw: dict[str, Any] = {"task_list": task_data, "tasks": []}
        if not isinstance(task_data, dict):
            return self._build_sign_stage_result(ok=False, message="获取 139 邮箱任务失败", raw=raw)
        task_list = task_data.get("result") or {}
        month_tasks = task_list.get("month") or []
        failures = 0
        finished = 0
        skip_ids = {1004, 1005, 1015, 1020}
        for task in month_tasks:
            task_id = int(task.get("id") or 0)
            task_name = self._strip_task_name(task)
            task_status = str(task.get("state") or "")
            if task_id in skip_ids:
                raw["tasks"].append({"task_id": task_id, "task_name": task_name, "status": "skipped"})
                continue
            if task_status == "FINISH":
                raw["tasks"].append({"task_id": task_id, "task_name": task_name, "status": "finished"})
                finished += 1
                continue
            click_data = self._click_legacy_market_task(jwt_token, task_id)
            ok = isinstance(click_data, dict) and (
                int(click_data.get("code", -1)) == 0
                or str(click_data.get("msg") or "").lower() == "success"
                or "result" in click_data
            )
            raw["tasks"].append(
                {
                    "task_id": task_id,
                    "task_name": task_name,
                    "status": "finished" if ok else "failed",
                    "raw": click_data,
                }
            )
            if ok:
                finished += 1
            else:
                failures += 1
        if not month_tasks:
            return self._build_sign_stage_result(ok=True, message="139 邮箱任务为空", raw=raw)
        message = f"139 邮箱任务处理完成，共 {len(month_tasks)} 项"
        if failures:
            message = f"{message}，失败 {failures} 项"
        return self._build_sign_stage_result(ok=failures == 0, message=message, raw=raw, finished=finished)

    def _fruit_headers(self, referer: str = "") -> dict[str, str]:
        return {
            "Host": "happy.mail.10086.cn",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": self.MARKET_USER_AGENT,
            "Referer": referer or f"{self.FRUIT_BASE_URL}wap/index.html?sourceid={self.FRUIT_SOURCE_ID}",
        }

    def _login_fruit_session(self) -> tuple[requests.Session, dict[str, Any]]:
        account = self._username or self._phone or self._parse_phone_from_authorization(self._authorization)
        token = self._market_sso_token or self._query_market_sso_token()
        if not account:
            raise RuntimeError("缺少账号信息，无法登录果园")
        if not token:
            raise RuntimeError("缺少果园 token")
        session = requests.Session()
        login_url = (
            f"{self.FRUIT_BASE_URL}login/caiyunsso.do?token={quote(token, safe='')}"
            f"&account={quote(account, safe='')}&targetSourceId={self.FRUIT_TARGET_SOURCE_ID}"
            f"&sourceid={self.FRUIT_SOURCE_ID}&enableShare=1"
        )
        self._request_text(
            "GET",
            login_url,
            headers={
                "Host": "happy.mail.10086.cn",
                "Upgrade-Insecure-Requests": "1",
                "User-Agent": self.MARKET_USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
                    "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"
                ),
                "Referer": "https://caiyun.feixin.10086.cn:7071/",
                "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            timeout=20,
            session=session,
        )
        userinfo = self._request_json(
            "GET",
            f"{self.FRUIT_BASE_URL}login/userinfo.do",
            headers=self._fruit_headers(login_url),
            timeout=20,
            session=session,
        )
        if not isinstance(userinfo, dict) or int(((userinfo.get("result") or {}).get("islogin")) or 0) != 1:
            raise RuntimeError("果园登录失败")
        return session, {"login": userinfo}

    def _run_fruit_stage(self) -> dict[str, Any]:
        session, raw = self._login_fruit_session()
        check_sign_data = self._request_json(
            "GET",
            f"{self.FRUIT_BASE_URL}task/checkinInfo.do",
            headers=self._fruit_headers(),
            timeout=20,
            session=session,
        )
        raw["checkin_info"] = check_sign_data
        today_checkin = int((((check_sign_data or {}).get("result") or {}).get("todayCheckin")) or 0)
        if today_checkin != 1:
            raw["checkin"] = self._request_json(
                "GET",
                f"{self.FRUIT_BASE_URL}task/checkin.do",
                headers=self._fruit_headers(),
                timeout=20,
                session=session,
            )
            raw["click_widget"] = self._request_json(
                "GET",
                f"{self.FRUIT_BASE_URL}user/clickCartoon.do",
                headers=self._fruit_headers(),
                params={"cartoonType": "widget"},
                timeout=20,
                session=session,
            )
            raw["click_color"] = self._request_json(
                "GET",
                f"{self.FRUIT_BASE_URL}user/clickCartoon.do",
                headers=self._fruit_headers(),
                params={"cartoonType": "color"},
                timeout=20,
                session=session,
            )
        task_list_data = self._request_json(
            "GET",
            f"{self.FRUIT_BASE_URL}task/taskList.do",
            headers=self._fruit_headers(),
            params={"clientType": "PE"},
            timeout=20,
            session=session,
        )
        task_state_data = self._request_json(
            "GET",
            f"{self.FRUIT_BASE_URL}task/taskState.do",
            headers=self._fruit_headers(),
            timeout=20,
            session=session,
        )
        raw["task_list"] = task_list_data
        raw["task_state"] = task_state_data
        if not isinstance(task_list_data, dict) or not isinstance(task_state_data, dict):
            return self._build_sign_stage_result(ok=False, message="获取果园任务列表失败", raw=raw)
        state_map = {int(item.get("taskId") or 0): int(item.get("taskState") or 0) for item in (task_state_data.get("result") or [])}
        handled: list[dict[str, Any]] = []
        failures = 0
        completed = 0
        for task in task_list_data.get("result") or []:
            task_id = int(task.get("taskId") or 0)
            task_name = str(task.get("taskName") or "")
            if task_id in {2002, 2003}:
                handled.append({"task_id": task_id, "task_name": task_name, "status": "skipped"})
                continue
            if state_map.get(task_id) == 2:
                handled.append({"task_id": task_id, "task_name": task_name, "status": "finished"})
                completed += 1
                continue
            do_data = self._request_json(
                "GET",
                f"{self.FRUIT_BASE_URL}task/doTask.do",
                headers=self._fruit_headers(),
                params={"taskId": task_id},
                timeout=20,
                session=session,
            )
            water_data = self._request_json(
                "GET",
                f"{self.FRUIT_BASE_URL}task/givenWater.do",
                headers=self._fruit_headers(),
                params={"taskId": task_id},
                timeout=20,
                session=session,
            )
            ok = bool((do_data or {}).get("success")) and bool((water_data or {}).get("success"))
            handled.append({"task_id": task_id, "task_name": task_name, "status": "finished" if ok else "failed", "do": do_data, "water": water_data})
            if ok:
                completed += 1
            else:
                failures += 1
        raw["handled_tasks"] = handled
        tree_info = self._request_json(
            "GET",
            f"{self.FRUIT_BASE_URL}user/treeInfo.do",
            headers=self._fruit_headers(),
            timeout=20,
            session=session,
        )
        raw["tree_info"] = tree_info
        watered = 0
        if bool((tree_info or {}).get("success")):
            result = tree_info.get("result") or {}
            tree_level = int(result.get("treeLevel") or 0)
            collect_water = int(result.get("collectWater") or 0)
            if tree_level in (2, 4, 6, 8):
                raw["open_box"] = self._request_json(
                    "GET",
                    f"{self.FRUIT_BASE_URL}prize/openBox.do",
                    headers=self._fruit_headers(),
                    timeout=20,
                    session=session,
                )
            watering_times = min(collect_water // 20, 5)
            water_logs: list[dict[str, Any]] = []
            for _ in range(watering_times):
                water_data = self._request_json(
                    "GET",
                    f"{self.FRUIT_BASE_URL}user/watering.do",
                    headers=self._fruit_headers(),
                    params={"isFast": 0},
                    timeout=20,
                    session=session,
                )
                water_logs.append(water_data if isinstance(water_data, dict) else {})
                if bool((water_data or {}).get("success")):
                    watered += 1
                self._sleep_with_budget(1.0)
            raw["watering"] = water_logs
        message = f"果园任务完成，处理 {len(handled)} 项"
        if watered:
            message = f"{message}，浇水 {watered} 次"
        if failures:
            message = f"{message}，失败 {failures} 项"
        return self._build_sign_stage_result(ok=failures == 0, message=message, raw=raw, finished=completed + watered)

    def _run_cloud_reward_stage(self, jwt_token: str) -> dict[str, Any]:
        info_data = self._query_market_signin_info(jwt_token)
        if int(info_data.get("code", -1)) != 0:
            raise RuntimeError(str(info_data.get("msg") or "查询云朵失败"))
        info_result = info_data.get("result") or {}
        pending_amount = int(info_result.get("toReceive") or 0)
        total_amount = int(info_result.get("total") or 0)
        receive_amount = 0
        raw: dict[str, Any] = {"info": info_data}
        if pending_amount:
            self._prepare_signin_center_session(for_receive=True)
            receive_data: dict[str, Any] | None = None
            receive_error = ""
            try:
                receive_data = self._market_request_json(
                    "GET",
                    f"{self.MARKET_BASE_URL}/ycloud/signin/page/receiveV2",
                    headers=self._build_receive_headers(jwt_token),
                    params={"client": "app"},
                    cookies=self._market_cookies(jwt_token),
                    timeout=20,
                )
            except Exception as exc:
                receive_error = str(exc)
            raw["receive"] = receive_data
            if receive_error:
                raw["receive_error"] = receive_error
            if isinstance(receive_data, dict) and int(receive_data.get("code", -1)) == 0:
                result = receive_data.get("result") or {}
                receive_amount = int(result.get("receive") or pending_amount)
                total_amount = int(result.get("total") or total_amount)
            else:
                latest_info_data = self._query_market_signin_info(jwt_token)
                raw["latest_info"] = latest_info_data
                latest_result = latest_info_data.get("result") or {}
                latest_pending = int(latest_result.get("toReceive") or pending_amount)
                latest_total = int(latest_result.get("total") or total_amount)
                pending_delta = pending_amount - latest_pending
                total_delta = latest_total - total_amount
                claimed_amount = total_delta or pending_delta or (pending_amount if latest_pending == 0 else 0)
                if claimed_amount > 0:
                    receive_amount = claimed_amount
                    total_amount = latest_total
        prize_url = f"https://caiyun.feixin.10086.cn/market/prizeApi/checkPrize/getUserPrizeLogPage?currPage=1&pageSize=15&_={self._current_millis()}"
        try:
            prize_data = self._request_json(
                "GET",
                prize_url,
                headers=self._market_headers(include_jwt=True, jwt_token=jwt_token),
                cookies=self._market_cookies(jwt_token),
                timeout=20,
            )
        except Exception as exc:
            prize_data = {"error": str(exc)}
        raw["prize"] = prize_data
        pending_rewards: list[str] = []
        if isinstance(prize_data, dict):
            for item in (((prize_data.get("result") or {}).get("result")) or []):
                if int(item.get("flag") or 0) == 1:
                    name = str(item.get("prizeName") or "").strip()
                    if name:
                        pending_rewards.append(name)
        message = f"云朵领取完成，当前 {total_amount} 云朵"
        if pending_rewards:
            message = f"{message}，待领取奖品 {len(pending_rewards)} 项"
        return self._build_sign_stage_result(
            ok=True,
            message=message,
            reward=receive_amount,
            raw=raw,
            total=total_amount,
            pending=pending_amount,
            pending_rewards=pending_rewards,
        )

    def _run_backup_stage(self, jwt_token: str) -> dict[str, Any]:
        backup_info = self._request_json("GET", "https://caiyun.feixin.10086.cn/market/backupgift/info", headers=self._market_headers(include_jwt=True, jwt_token=jwt_token), cookies=self._market_cookies(jwt_token), timeout=20)
        raw: dict[str, Any] = {"backup_info": backup_info}
        if isinstance(backup_info, dict):
            state = (backup_info.get("result") or {}).get("state")
            if state == 0:
                raw["backup_receive"] = self._request_json("GET", "https://caiyun.feixin.10086.cn/market/backupgift/receive", headers=self._market_headers(include_jwt=True, jwt_token=jwt_token), cookies=self._market_cookies(jwt_token), timeout=20)
        expand_data = self._market_request_json("GET", f"{self.MARKET_BASE_URL}/ycloud/signin/page/taskExpansion", headers=self._market_headers(include_jwt=True, jwt_token=jwt_token), cookies=self._market_cookies(jwt_token), timeout=20)
        raw["expand"] = expand_data
        result = (expand_data or {}).get("result") or {}
        if result.get("preMonthBackup") and not result.get("curMonthBackupTaskAccept") and result.get("acceptDate"):
            raw["expand_receive"] = self._market_request_json("GET", f"{self.MARKET_BASE_URL}/ycloud/signin/page/receiveTaskExpansion", headers=self._market_headers(include_jwt=True, jwt_token=jwt_token), params={"acceptDate": result.get("acceptDate")}, cookies=self._market_cookies(jwt_token), timeout=20)
        return self._build_sign_stage_result(ok=True, message="备份奖励链路执行完成", raw=raw)

    def _run_wx_sign_stage(self, jwt_token: str) -> dict[str, Any]:
        data = self._request_json("GET", "https://caiyun.feixin.10086.cn/market/playoffic/followSignInfo?isWx=true", headers=self._market_headers(include_jwt=True, jwt_token=jwt_token), cookies=self._market_cookies(jwt_token), timeout=20)
        if not isinstance(data, dict) or str(data.get("msg") or "") != "success":
            return self._build_sign_stage_result(ok=False, message=str((data or {}).get("msg") or "公众号签到失败"), raw=data)
        today = bool(((data.get("result") or {}).get("todaySignIn")))
        return self._build_sign_stage_result(ok=today, message="公众号签到成功" if today else "可能未绑定公众号", raw=data)

    def _run_shake_stage(self, jwt_token: str) -> dict[str, Any]:
        prizes: list[str] = []
        error_message = ""
        try:
            for _ in range(15):
                remaining = self._remaining_sign_in_seconds()
                if remaining is not None and remaining < 2.0:
                    break
                data = self._request_json(
                    "POST",
                    "https://caiyun.feixin.10086.cn:7071/market/shake-server/shake/shakeIt?flag=1",
                    headers=self._jwt_activity_headers(jwt_token),
                    cookies=self._jwt_activity_cookies(jwt_token),
                    timeout=20,
                )
                prize = (((data or {}).get("result") or {}).get("shakePrizeconfig") or {}).get("name")
                if prize:
                    prizes.append(str(prize))
                self._sleep_with_budget(1)
        except Exception as exc:
            error_message = str(exc)
        if prizes:
            return self._build_sign_stage_result(ok=True, message=f"摇一摇获得 {len(prizes)} 次奖励", raw={"prizes": prizes, "error": error_message or None})
        return self._build_sign_stage_result(ok=False, message=error_message or "摇一摇未中奖", raw={"prizes": prizes, "error": error_message or None})

    def _run_draw_stage(self, jwt_token: str) -> dict[str, Any]:
        info = self._request_json("GET", "https://caiyun.feixin.10086.cn/market/playoffic/drawInfo", headers=self._market_headers(include_jwt=True, jwt_token=jwt_token), cookies=self._market_cookies(jwt_token), timeout=20)
        raw: dict[str, Any] = {"info": info, "draws": []}
        if not isinstance(info, dict) or str(info.get("msg") or "") != "success":
            return self._build_sign_stage_result(ok=False, message=str((info or {}).get("msg") or "抽奖查询失败"), raw=raw)
        remain_num = int(((info.get("result") or {}).get("surplusNumber")) or 0)
        if remain_num <= 49:
            return self._build_sign_stage_result(ok=True, message=f"剩余抽奖次数 {remain_num}", raw=raw)
        draw = self._request_json("GET", "https://caiyun.feixin.10086.cn/market/playoffic/draw", headers=self._market_headers(include_jwt=True, jwt_token=jwt_token), cookies=self._market_cookies(jwt_token), timeout=20)
        raw["draws"].append(draw)
        prize_name = (((draw or {}).get("result") or {}).get("prizeName") or "")
        return self._build_sign_stage_result(ok=int((draw or {}).get("code", -1)) == 0, message=f"抽奖成功，获得 {prize_name}" if prize_name else "抽奖完成", raw=raw)

    def _red_packet_login_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "User-Agent": self.MARKET_USER_AGENT,
            "Accept": "*/*",
            "Host": "cpactiv.buy.139.com",
        }

    def _red_packet_market_headers(self, jwt_token: str) -> dict[str, str]:
        return {
            **self._market_headers(include_jwt=True, jwt_token=jwt_token),
            "Referer": self._build_market_page_url(self.RED_PACKET_SOURCE_ID),
        }

    def _red_packet_request(self, path: str, body: dict[str, Any], *, jwt_token: str = "") -> dict[str, Any]:
        data = self._market_request_json(
            "POST",
            f"{self.RED_PACKET_BASE_URL}{path}",
            headers=self._red_packet_market_headers(jwt_token),
            json_body=body,
            cookies=self._market_cookies(jwt_token),
            timeout=20,
        )
        return data if isinstance(data, dict) else {}

    def _login_red_packet(self) -> dict[str, Any]:
        token = self._query_market_sso_token(self.RED_PACKET_SOURCE_ID)
        resp = requests.post(
            f"{self.RED_PACKET_BASE_URL}/ticket/login",
            headers=self._red_packet_login_headers(),
            json={"token": token, "sourceId": self.RED_PACKET_SOURCE_ID},
            timeout=self._effective_timeout(20),
        )
        if resp.status_code != 200:
            raise RuntimeError(f"红包派对登录失败: HTTP {resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("红包派对登录失败: 接口无响应")
        if int(data.get("code", -1)) != 0:
            raise RuntimeError(str(data.get("msg") or "红包派对登录失败"))
        header = data.get("header") or {}
        if str(header.get("status") or "") != "200":
            raise RuntimeError(str(header.get("respMsg") or "红包派对登录失败"))
        result = data.get("result") or {}
        self._red_packet_token = str(result.get("token") or "")
        self._red_packet_mobile = str(result.get("mobile") or self._username or self._phone or "")
        self._red_packet_jwt_token = str(result.get("jwtToken") or "")
        if self._red_packet_jwt_token:
            self._build_market_context(self._red_packet_jwt_token)
        return {
            "token": self._red_packet_token,
            "mobile": self._red_packet_mobile,
            "jwt_token": self._red_packet_jwt_token,
        }

    def _sign_red_packet(self, mobile: str, jwt_token: str) -> dict[str, Any]:
        sign = hashlib.md5(f"{self.RED_PACKET_SIGN_KEY}mobile{mobile}".encode("utf-8")).hexdigest()
        return self._red_packet_request("/sign/signBySourceId", {"mobile": mobile, "sign": sign, "sourceId": self.RED_PACKET_SOURCE_ID, "version": self.RED_PACKET_VERSION, "channelSrc": self.RED_PACKET_CHANNEL_SRC}, jwt_token=jwt_token)

    def _get_red_packet_task_list(self, token: str, jwt_token: str) -> dict[str, Any]:
        return self._red_packet_request("/taskCenter/task", {"appId": self.RED_PACKET_APP_ID, "sourceId": self.RED_PACKET_SOURCE_ID, "token": token}, jwt_token=jwt_token)

    def _get_red_packet_balance(self, token: str, jwt_token: str) -> dict[str, Any]:
        return self._red_packet_request("/taskCenter/balance", {"appId": self.RED_PACKET_APP_ID, "sourceId": self.RED_PACKET_SOURCE_ID, "token": token}, jwt_token=jwt_token)

    def _get_red_packet_question(self, token: str, task_code: str, jwt_token: str) -> dict[str, Any]:
        return self._red_packet_request("/taskCenter/question", {"appId": self.RED_PACKET_APP_ID, "sourceId": self.RED_PACKET_SOURCE_ID, "token": token, "taskCode": task_code}, jwt_token=jwt_token)

    def _answer_red_packet_question(self, token: str, task_code: str, option_id: str, jwt_token: str) -> dict[str, Any]:
        return self._red_packet_request("/taskCenter/answer", {"appId": self.RED_PACKET_APP_ID, "sourceId": self.RED_PACKET_SOURCE_ID, "token": token, "taskCode": task_code, "optionId": option_id}, jwt_token=jwt_token)

    def _handle_red_packet_task(self, token: str, jwt_token: str, task: dict[str, Any]) -> dict[str, Any]:
        task_name = str(task.get("taskName") or "")
        task_code = str(task.get("taskCode") or "")
        state = int(task.get("state") or 0)
        if state == 3:
            return {"task_name": task_name, "task_code": task_code, "status": "finished"}
        if task_code in self.RED_PACKET_MANUAL_TASKS:
            return {"task_name": task_name, "task_code": task_code, "status": "manual", "message": self.RED_PACKET_MANUAL_TASKS[task_code]}
        if state == 0:
            click_data = self._red_packet_request("/taskCenter/click", {"appId": self.RED_PACKET_APP_ID, "sourceId": self.RED_PACKET_SOURCE_ID, "token": token, "taskCode": task_code}, jwt_token=jwt_token)
            header = click_data.get("header") or {}
            if int(header.get("status") or 0) != 200:
                return {"task_name": task_name, "task_code": task_code, "status": "failed", "message": str(header.get("respMsg") or "点击失败")}
            done = click_data.get("data") or {}
            if int(done.get("state") or 0) == 2:
                return {"task_name": task_name, "task_code": task_code, "status": "running"}
            return {"task_name": task_name, "task_code": task_code, "status": "clicked"}
        if state == 1:
            return {"task_name": task_name, "task_code": task_code, "status": "running"}
        if state == 2:
            if task_code in self.RED_PACKET_BROWSE_TASKS:
                return {"task_name": task_name, "task_code": task_code, "status": "manual", "message": "需跳转活动页完成"}
            if task_code in self.RED_PACKET_DIRECT_TASKS:
                complete = self._red_packet_request("/taskCenter/complete", {"appId": self.RED_PACKET_APP_ID, "sourceId": self.RED_PACKET_SOURCE_ID, "token": token, "taskCode": task_code}, jwt_token=jwt_token)
                header = complete.get("header") or {}
                return {"task_name": task_name, "task_code": task_code, "status": "finished" if int(header.get("status") or 0) == 200 else "failed", "raw": complete}
            if task_code.startswith("ANSWER_"):
                question = self._get_red_packet_question(token, task_code, jwt_token)
                qdata = question.get("data") or {}
                question_text = str(qdata.get("question") or qdata.get("questionText") or "")
                options = qdata.get("options") or qdata.get("questionOptionList") or []
                answer = self.RED_PACKET_KNOWN_ANSWERS.get(question_text, "")
                if not answer and options:
                    answer = str((options[0] or {}).get("optionDesc") or (options[0] or {}).get("name") or "")
                option_id = ""
                for opt in options:
                    desc = str(opt.get("optionDesc") or opt.get("name") or "")
                    if desc == answer:
                        option_id = str(opt.get("id") or opt.get("optionId") or "")
                        break
                if option_id:
                    answer_data = self._answer_red_packet_question(token, task_code, option_id, jwt_token)
                    header = answer_data.get("header") or {}
                    return {"task_name": task_name, "task_code": task_code, "status": "finished" if int(header.get("status") or 0) == 200 else "failed", "raw": answer_data}
            return {"task_name": task_name, "task_code": task_code, "status": "manual", "message": "需手动完成"}
        return {"task_name": task_name, "task_code": task_code, "status": "unknown"}

    def _run_red_packet_stage(self) -> dict[str, Any]:
        login = self._login_red_packet()
        token = str(login.get("token") or "")
        mobile = str(login.get("mobile") or self._username or self._phone or "")
        jwt_token = str(login.get("jwt_token") or self._red_packet_jwt_token or self._market_jwt_token or "")
        if not token:
            raise RuntimeError("红包派对 token 为空")
        sign_data = self._sign_red_packet(mobile, jwt_token)
        task_data = self._get_red_packet_task_list(token, jwt_token)
        header = task_data.get("header") or {}
        if int(header.get("status") or 0) != 200:
            raise RuntimeError(str(header.get("errMsg") or header.get("respMsg") or "获取红包派对任务失败"))
        task_list = task_data.get("data") or {}
        handled: list[dict[str, Any]] = []
        for group in ("SIGN", "NOVICE", "DAILY", "MONTHLY"):
            for task in task_list.get(group) or []:
                if group == "SIGN" and int(task.get("state") or 0) != 3:
                    handled.append({"task_name": str(task.get("taskName") or "签到"), "task_code": str(task.get("taskCode") or ""), "status": "finished" if int(sign_data.get("code", -1)) == 0 else "failed", "raw": sign_data})
                    continue
                handled.append(self._handle_red_packet_task(token, jwt_token, task))
        balance = self._get_red_packet_balance(token, jwt_token)
        amount = ((balance.get("data") or {}).get("amount")) or 0
        return self._build_sign_stage_result(ok=True, message=f"红包派对任务完成，余额 {amount}", raw={"login": login, "sign": sign_data, "tasks": handled, "balance": balance})

    def sign_in(self) -> Dict[str, Any]:
        self._ensure_authenticated()
        try:
            info = self._get_user_info()
        except Exception:
            info = {}
        if isinstance(info, dict):
            self._update_identity_from_user_info(info)
        context_error = ""
        jwt_token = ""
        try:
            context = self._prepare_market_context()
            jwt_token = str(context.get("jwt_token") or "")
        except Exception as exc:
            context_error = str(exc)

        stages = {
            "signin": self._run_sign_stage(self._sign_in_market_stage, "signin", required_jwt=True, jwt_token=jwt_token),
            "click": self._run_sign_stage(self._run_market_click_stage, "click", required_jwt=True, jwt_token=jwt_token),
            "cloud_tasks": self._run_sign_stage(self._run_cloud_tasks_stage, "cloud_tasks", required_jwt=True, jwt_token=jwt_token),
            "cloud_game": self._run_sign_stage(self._run_cloud_game_stage, "cloud_game", required_jwt=True, jwt_token=jwt_token),
            "fruit": self._run_sign_stage(self._run_fruit_stage, "fruit"),
            "wxsign": self._run_sign_stage(self._run_wx_sign_stage, "wxsign", required_jwt=True, jwt_token=jwt_token),
            "shake": self._run_sign_stage(self._run_shake_stage, "shake", required_jwt=True, jwt_token=jwt_token),
            "draw": self._run_sign_stage(self._run_draw_stage, "draw", required_jwt=True, jwt_token=jwt_token),
            "backup": self._run_sign_stage(self._run_backup_stage, "backup", required_jwt=True, jwt_token=jwt_token),
            "notice": self._run_sign_stage(self._run_notice_stage, "notice", required_jwt=True, jwt_token=jwt_token),
            "mail_tasks": self._run_sign_stage(self._run_mail_tasks_stage, "mail_tasks", required_jwt=True, jwt_token=jwt_token),
            "red_packet": self._run_sign_stage(self._run_red_packet_stage, "red_packet"),
            "cloud_reward": self._run_sign_stage(self._run_cloud_reward_stage, "cloud_reward", required_jwt=True, jwt_token=jwt_token),
        }
        success_count = sum(1 for item in stages.values() if item.get("ok"))
        skipped_count = sum(1 for item in stages.values() if item.get("skipped"))
        reward = sum(int(item.get("reward") or 0) for item in stages.values())
        sign_message = str((stages.get("signin") or {}).get("message") or ("签到上下文初始化失败" if context_error else "签到阶段已跳过"))
        remaining = self._remaining_sign_in_seconds()
        summary_message = f"{sign_message}；链路执行完成，成功 {success_count} 项，跳过 {skipped_count} 项"
        return {
            "supported": True,
            "ok": True,
            "reward": reward,
            "message": sign_message,
            "raw": {
                "context_error": context_error or None,
                "summary_message": summary_message,
                "remaining_budget_seconds": round(remaining, 2) if remaining is not None else None,
                "stages": stages,
            },
        }

    def _parse_timestamp(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if not text:
            return 0
        if text.isdigit():
            if len(text) == 14:
                try:
                    return int(datetime.strptime(text, "%Y%m%d%H%M%S").timestamp())
                except Exception:
                    return 0
            if len(text) == 8:
                try:
                    return int(datetime.strptime(text, "%Y%m%d").timestamp())
                except Exception:
                    return 0
            return int(text)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return int(datetime.strptime(text[:19], fmt).timestamp())
            except Exception:
                continue
        return 0

    def extract_url(self, url: str) -> Tuple[Optional[str], str, Any, List]:
        raw = str(url or "").strip()
        if not raw:
            return None, "", "root", []

        text = raw.replace("？", "?").replace("（", "(").replace("）", ")")
        compact = re.sub(r"\s+", "", text)
        try:
            compact = unquote(compact)
        except Exception:
            pass

        passwd = ""
        pwd_patterns = [
            r"passwd=([a-zA-Z0-9]{4,8})",
            r"pwd=([a-zA-Z0-9]{4,8})",
            r"密码[：:]\s*([a-zA-Z0-9]{4,8})",
            r"提取码[：:]\s*([a-zA-Z0-9]{4,8})",
            r"\(([a-zA-Z0-9]{4,8})\)",
        ]
        for pat in pwd_patterns:
            match = re.search(pat, compact, flags=re.I)
            if match:
                passwd = str(match.group(1) or "").strip()
                break

        if re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", raw) and "/" not in raw:
            return raw, passwd, "root", []

        extracted_url = ""
        direct_match = re.search(r"(https?://(?:yun|caiyun)\.139\.com[^\s]*)", text, flags=re.I)
        if direct_match:
            extracted_url = direct_match.group(1)
        elif re.search(r"(?:yun|caiyun)\.139\.com", text, flags=re.I):
            extracted_url = "https://" + re.search(r"((?:yun|caiyun)\.139\.com[^\s]*)", text, flags=re.I).group(1)
        else:
            extracted_url = text

        try:
            parsed = urlparse(extracted_url)
        except Exception:
            return None, passwd, "root", []

        if not parsed.scheme and parsed.path:
            parsed = urlparse("https://" + extracted_url.lstrip("/"))

        pdir_fid = "root"
        frag = str(parsed.fragment or "").strip()
        frag_path, frag_query = (frag.split("?", 1) + [""])[:2] if frag else ("", "")
        frag_qs = parse_qs(frag_query or "")
        generic_share_fid = ""
        if frag_path:
            m_generic = re.search(r"(?:^|/)list/share/([^/?#]+)", frag_path)
            if m_generic:
                generic_share_fid = str(m_generic.group(1) or "").strip()
                if generic_share_fid:
                    pdir_fid = generic_share_fid

        query = parse_qs(parsed.query or "")
        fid_from_query = str((query.get("fid") or [""])[0] or "").strip()
        if fid_from_query and fid_from_query not in ("0", "root"):
            pdir_fid = fid_from_query
        fid_from_frag = str((frag_qs.get("fid") or [""])[0] or "").strip()
        if fid_from_frag and fid_from_frag not in ("0", "root"):
            pdir_fid = fid_from_frag

        link_id = (query.get("linkID") or query.get("linkId") or [""])[0]
        if not link_id and parsed.query and re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", parsed.query):
            link_id = parsed.query
        if not link_id and parsed.fragment and not generic_share_fid:
            link_id = (frag_qs.get("linkID") or frag_qs.get("linkId") or [""])[0]
            if not link_id:
                frag_parts = re.split(r"[/?]", frag_path)
                candidate = frag_parts[-1] if frag_parts else ""
                if re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", candidate or ""):
                    link_id = candidate
        if not link_id:
            match = re.search(r"linkID=([a-zA-Z0-9_-]{4,64})", compact, flags=re.I)
            if match:
                link_id = match.group(1)

        return (link_id or None), passwd, pdir_fid, []

    def _get_share_info(self, link_id: str, passwd: str = "", pdir_fid: str = "root", start_num: int = 1, end_num: int = 200) -> dict[str, Any] | None:
        payload = {
            "getOutLinkInfoReq": {
                "account": self._phone or "",
                "linkID": link_id,
                "passwd": passwd or "",
                "pCaID": pdir_fid or "root",
                "caSrt": 0,
                "coSrt": 0,
                "srtDr": 1,
                "bNum": start_num,
                "eNum": end_num,
            }
        }
        self._debug_log_json("share.request", payload)
        data = self._share_kd_post("/yun-share/richlifeApp/devapp/IOutLink/getOutLinkInfoV6", payload)
        self._debug_log_json("share.response", data)
        return data if isinstance(data, dict) else None

    def get_stoken(self, pwd_id: str, passcode: str = "") -> Dict:
        if not pwd_id:
            return {"status": 400, "message": "分享链接无效", "data": {}}
        try:
            info = self._get_share_info(pwd_id, passcode or "", "root", 1, 1)
        except Exception as exc:
            return {"status": 500, "message": str(exc), "data": {}}
        if not info:
            return {"status": 404, "message": "分享不存在或认证失败", "data": {}}
        stoken = json.dumps({"linkID": pwd_id, "passwd": passcode or ""}, ensure_ascii=False)
        return {"status": 200, "message": "success", "data": {"stoken": stoken}}

    def _parse_share_token(self, stoken: str) -> dict[str, Any]:
        raw = str(stoken or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {"passwd": raw}

    def get_detail(
        self,
        pwd_id: str,
        stoken: str,
        pdir_fid: str,
        _fetch_share: int = 0,
        fetch_share_full_path: int = 0,
    ) -> Dict:
        if not pwd_id:
            return {"code": 1, "message": "分享链接无效", "data": {"list": []}}
        token = self._parse_share_token(stoken)
        passwd = str(token.get("passwd") or "")
        pdir = str(pdir_fid or "root")
        try:
            info = self._get_share_info(pwd_id, passwd, pdir, 1, 200)
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {"list": []}}
        if not info:
            return {"code": 1, "message": "获取分享目录失败", "data": {"list": []}}

        data_list: list[dict[str, Any]] = []
        for folder in info.get("caLst") or []:
            fid = str(folder.get("catalogID") or folder.get("caID") or "")
            name = str(folder.get("catalogName") or folder.get("caName") or "")
            if not fid or not name:
                continue
            share_token = json.dumps(
                {
                    "path": str(folder.get("path") or ""),
                    "pid": str(pdir or "root"),
                    "dir": 1,
                    "name": name,
                },
                ensure_ascii=False,
            )
            data_list.append(
                {
                    "fid": fid,
                    "file_name": name,
                    "dir": True,
                    "size": 0,
                    "updated_at": self._parse_timestamp(
                        folder.get("udTime") or folder.get("updateTime") or folder.get("lastUpdateTime")
                    ),
                    "share_fid_token": share_token,
                }
            )
        for file_item in info.get("coLst") or []:
            fid = str(file_item.get("contentID") or file_item.get("coID") or "")
            name = str(file_item.get("contentName") or file_item.get("coName") or "")
            if not fid or not name:
                continue
            share_token = json.dumps(
                {
                    "path": str(file_item.get("path") or ""),
                    "pid": str(pdir or "root"),
                    "dir": 0,
                    "name": name,
                },
                ensure_ascii=False,
            )
            size = file_item.get("coSize") or file_item.get("contentSize") or file_item.get("size") or 0
            try:
                size = int(size)
            except Exception:
                size = 0
            data_list.append(
                {
                    "fid": fid,
                    "file_name": name,
                    "dir": False,
                    "size": size,
                    "updated_at": self._parse_timestamp(
                        file_item.get("udTime") or file_item.get("updateTime") or file_item.get("updatedAt")
                    ),
                    "share_fid_token": share_token,
                }
            )
        return {"code": 0, "message": "success", "data": {"list": data_list, "full_path": []}}

    def _list_disk_dir(self, parent_file_id: str = "/", *, cursor: str | None = None) -> dict[str, Any]:
        body = {
            "pageInfo": {"pageSize": 1000, "pageCursor": cursor},
            "orderBy": "updated_at",
            "orderDirection": "DESC",
            "parentFileId": parent_file_id or "/",
            "imageThumbnailStyleList": ["Small", "Large"],
        }
        self._debug_log_json("disk.request", body)
        data = self._personal_kd_post("/hcy/file/list", body, parent_file_id or "/")
        self._debug_log_json("disk.response", data)
        if not isinstance(data, dict):
            raise RuntimeError("获取目录列表失败")
        return data

    def ls_dir(self, pdir_fid: str, max_items: int = 0, **kwargs) -> Dict:
        try:
            parent_file_id = "/" if str(pdir_fid or "") in ("", "0", "/", "root") else str(pdir_fid)
            items: list[dict[str, Any]] = []
            cursor = None
            while True:
                payload = self._list_disk_dir(parent_file_id, cursor=cursor)
                batch = payload.get("items") or payload.get("fileList") or []
                for item in batch:
                    file_type = item.get("fileType")
                    if file_type is None:
                        file_type = item.get("category")
                    if file_type is None:
                        file_type = item.get("type")
                    if file_type is None:
                        file_type = item.get("isFolder")
                    normalized_type = str(file_type or "").strip().lower()
                    if normalized_type.isdigit():
                        is_dir = int(normalized_type) == 0
                    else:
                        is_dir = normalized_type in {"folder", "dir", "directory", "d"}
                    size = item.get("size")
                    try:
                        size = int(size) if size is not None else 0
                    except Exception:
                        size = 0
                    items.append(
                        {
                            "fid": str(item.get("fileId") or item.get("id") or ""),
                            "file_name": str(item.get("name") or item.get("fileName") or ""),
                            "dir": is_dir,
                            "size": size,
                            "updated_at": self._parse_timestamp(item.get("updatedAt") or item.get("updateTime")),
                            "share_fid_token": "",
                        }
                    )
                    if max_items > 0 and len(items) >= max_items:
                        return {"code": 0, "message": "success", "data": {"list": items[:max_items]}}
                cursor = payload.get("nextPageCursor") or ((payload.get("pageInfo") or {}).get("nextPageCursor"))
                if not cursor or not batch:
                    break
            return {"code": 0, "message": "success", "data": {"list": items}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {"list": []}}

    def _find_child_folder(self, parent_id: str, folder_name: str) -> str:
        listing = self.ls_dir(parent_id, max_items=0)
        for item in (((listing or {}).get("data") or {}).get("list") or []):
            if not item.get("dir"):
                continue
            if str(item.get("file_name") or "") == str(folder_name):
                return str(item.get("fid") or "")
        return ""

    def mkdir(self, dir_path: str) -> Dict:
        try:
            normalized = re.sub(r"/{2,}", "/", f"/{str(dir_path or '').strip()}").rstrip("/")
            if normalized in ("", "/"):
                return {"code": 0, "message": "success", "data": {"fid": "0"}}
            parent_id = "/"
            for name in [seg for seg in normalized.split("/") if seg]:
                exists = self._find_child_folder(parent_id, name)
                if exists:
                    parent_id = exists
                    continue
                body = {"parentFileId": parent_id or "/", "name": name, "type": "folder"}
                data = self._personal_kd_post("/hcy/file/create", body, parent_id or "/")
                new_fid = str((data or {}).get("fileId") or (data or {}).get("id") or "")
                if not new_fid:
                    raise RuntimeError("创建目录失败")
                parent_id = new_fid
            return {"code": 0, "message": "success", "data": {"fid": str(parent_id if parent_id != "/" else "0")}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def rename(self, fid: str, file_name: str) -> Dict:
        try:
            data = self._personal_kd_post("/hcy/file/update", {"fileId": str(fid), "name": str(file_name)}, "/")
            return {"code": 0, "message": "success", "data": data or {}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def delete(self, filelist: List[str]) -> Dict:
        try:
            if not filelist:
                return {"code": 0, "message": "success", "data": {}}
            data = self._personal_kd_post("/hcy/recyclebin/batchTrash", {"fileIds": [str(x) for x in filelist if str(x).strip()]}, "/")
            task_id = str((data or {}).get("taskId") or (data or {}).get("taskID") or "")
            if task_id:
                for _ in range(10):
                    time.sleep(1)
                    task = self._personal_kd_post("/hcy/task/get", {"taskId": task_id}, "/")
                    status = str((task or {}).get("status") or (task or {}).get("taskStatus") or "")
                    if status in ("success", "2"):
                        break
                    if status in ("failed", "3"):
                        raise RuntimeError("删除任务失败")
            return {"code": 0, "message": "success", "data": {}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def get_fids(self, file_paths: List[str]) -> List[Dict]:
        result: list[dict[str, str]] = []
        for path in file_paths or []:
            normalized = re.sub(r"/{2,}", "/", f"/{str(path or '').strip()}").rstrip("/")
            if normalized in ("", "/"):
                result.append({"file_path": "/", "fid": "0"})
                continue
            parent_id = "/"
            ok = True
            for name in [seg for seg in normalized.split("/") if seg]:
                found = self._find_child_folder(parent_id, name)
                if not found:
                    ok = False
                    break
                parent_id = found
            if ok:
                result.append({"file_path": normalized, "fid": str(parent_id if parent_id != "/" else "0")})
        return result

    def save_file(
        self,
        fid_list: List[str],
        fid_token_list: List[str],
        to_pdir_fid: str,
        pwd_id: str,
        stoken: str,
        file_names: List[str] | None = None,
    ) -> Dict:
        try:
            if not fid_list:
                return {"code": 0, "message": "success", "data": {"task_id": "", "save_as_top_fids": [], "_sync": True}}

            token = self._parse_share_token(stoken)
            passwd = str(token.get("passwd") or "")
            co_path_list: list[str] = []
            ca_path_list: list[str] = []
            for idx, fid in enumerate(fid_list):
                fid_token = str(fid_token_list[idx] or "") if idx < len(fid_token_list or []) else ""
                try:
                    payload = json.loads(fid_token) if fid_token else {}
                except Exception:
                    payload = {}
                path = str(payload.get("path") or fid or "").strip()
                if not path:
                    continue
                if int(payload.get("dir") or 0):
                    ca_path_list.append(path)
                else:
                    co_path_list.append(path)
            need_password = bool(passwd)
            target_catalog_id = "/" if str(to_pdir_fid or "") in ("", "0", "/", "root") else str(to_pdir_fid)
            data = self._share_kd_post(
                "/yun-share/richlifeApp/devapp/IBatchOprTask/createOuterLinkBatchOprTask",
                {
                    "createOuterLinkBatchOprTaskReq": {
                        "msisdn": self._phone or "",
                        "ownerAccount": "",
                        "taskType": 1,
                        "linkID": str(pwd_id),
                        "needPassword": need_password,
                        "taskInfo": {
                            "linkID": str(pwd_id),
                            "needPassword": need_password,
                            "contentInfoList": co_path_list,
                            "catalogInfoList": ca_path_list,
                            "newCatalogID": target_catalog_id,
                        },
                    }
                },
            )
            task_id = str((data or {}).get("taskID") or (data or {}).get("taskId") or "")

            before_items: dict[str, str] = {}
            if file_names:
                before_items = self.snapshot_dest_dir_items(target_catalog_id, max_items=1000)

            aligned_fids = self.align_saved_fids_from_dir(
                target_catalog_id,
                file_names,
                before_items=before_items,
                max_items=1000,
                timeout_seconds=60,
                interval_seconds=1.5,
                accept_partial_best=True,
            )

            return {
                "code": 0,
                "message": "success",
                "data": {
                    "task_id": task_id,
                    "save_as_top_fids": aligned_fids,
                    "_sync": True,
                },
            }
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def query_task(self, task_id: str) -> Dict:
        if not str(task_id or "").strip():
            return {"code": 0, "message": "ok", "data": {"status": 2, "save_as": {"save_as_top_fids": []}}}
        try:
            payload = self._personal_kd_post("/hcy/task/get", {"taskId": str(task_id)}, "/")
        except Exception:
            payload = {}
        status = str((payload or {}).get("status") or (payload or {}).get("taskStatus") or "2")
        if status in ("success", "2"):
            normalized_status: int | str = 2
        elif status in ("failed", "3"):
            normalized_status = 3
        else:
            normalized_status = status or 1
        return {
            "code": 0 if normalized_status != 3 else 1,
            "message": "ok" if normalized_status != 3 else str((payload or {}).get("message") or "任务失败"),
            "data": {
                "status": normalized_status,
                "save_as": {"save_as_top_fids": []},
            },
        }
