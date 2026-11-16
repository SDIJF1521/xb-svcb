"""插件市场（plugin market）索引解析规则。

本模块只承载「插件市场」这一用例所需的纯解析与归一化规则：从市场索引原文
中取出插件记录、生成稳定的插件 ID、校验插件 ID 与 GitHub 地址白名单，并把
不同上游写法的市场条目归一化成前端可直接渲染的字典。

这里的函数都是纯函数：不读文件、不发网络请求、不依赖配置、存储或任何
基础设施。插件服务（``plugin_service.PluginService``）负责 IO 与编排，本模块
只负责「市场数据长什么样才算合法」，因此可以独立测试与复用。
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "is_github_url",
    "is_valid_id",
    "market_id",
    "market_records",
    "normalise_market_item",
    "parse_market_payload",
]

# 插件 ID 同时用作安装目录名和前端标识：3-64 位小写安全字符。
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
# 市场索引允许的 GitHub HTTPS 主机（网页/API/raw 下载域名）。
GITHUB_HOSTS = frozenset({"github.com", "api.github.com", "githubusercontent.com"})
GITHUB_HOST_SUFFIXES = (".github.com", ".githubusercontent.com")
# 市场索引可以用的记录字段名，按优先级排列。
MARKET_RECORD_KEYS = ("plugins", "items")
# 生成 slug 时替换掉的非法字符。
_ID_SLUG_CLEANER = re.compile(r"[^a-z0-9._-]+")
# 市场索引的 JSON5 容错：块注释、行注释、尾逗号。
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"(?m)^\s*//.*$")
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def parse_market_payload(raw: str) -> Any:
    """解析插件市场索引原文，容忍 JSON5 的注释与尾逗号。

    先按严格 JSON 解析；失败后再逐项剥离 ``/* */``、``//`` 注释和尾逗号重试。
    两次都失败时抛出 :class:`ValueError`（而不是 ``JSONDecodeError``），
    因为对调用方来说这是「市场索引格式无效」，由调用方决定错误文案。
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        without_blocks = _BLOCK_COMMENT.sub("", raw)
        without_line_comments = _LINE_COMMENT.sub("", without_blocks)
        without_trailing_commas = _TRAILING_COMMA.sub(r"\1", without_line_comments)
        try:
            return json.loads(without_trailing_commas)
        except json.JSONDecodeError as exc:
            raise ValueError(str(exc)) from exc


def market_records(payload: Any) -> list[Any]:
    """从市场索引中取出插件记录列表。

    顶层是数组时直接使用；是对象时依次尝试 ``plugins`` / ``items`` 字段；
    其他形态（含字段类型不对）一律返回空列表，不抛异常。
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in MARKET_RECORD_KEYS:
            records = payload.get(key)
            if isinstance(records, list):
                return records
    return []


def market_id(value: str) -> str:
    """把上游任意标识折叠成符合插件 ID 规则的 slug（最多 64 字符）。

    过短的 slug 统一加 ``plugin-`` 前缀，避免安装目录名和前端标识过短。
    """
    cleaned = _ID_SLUG_CLEANER.sub("-", value.lower()).strip("._-")
    if len(cleaned) < 3:
        cleaned = f"plugin-{cleaned}".strip("-")
    return cleaned[:64]


def is_valid_id(value: str) -> bool:
    """判断字符串是否是合法的插件 ID（安装目录名 / 前端标识）。"""
    return bool(ID_PATTERN.fullmatch(value))


def is_github_url(value: str) -> bool:
    """判断地址是否是可信的 GitHub HTTPS 地址。

    插件市场索引与插件包只允许来自 github.com / api.github.com 及其子域、
    githubusercontent.com 及其子域，且必须是 HTTPS。
    """
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host in GITHUB_HOSTS or host.endswith(GITHUB_HOST_SUFFIXES)
    )


def normalise_market_item(item: Any) -> dict[str, Any] | None:
    """把一条市场记录归一化成前端渲染用的字典。

    ``id`` / ``module_name`` / ``project_link`` / ``name`` 互相兜底；非 GitHub 的
    下载地址会被丢弃（置空），tags 支持字符串或 ``{label, color}`` 对象。
    记录不是字典或归一化后 ID 非法时返回 ``None``，由调用方跳过。
    """
    if not isinstance(item, dict):
        return None
    module_name = str(item.get("module_name") or item.get("id") or "").strip()
    raw_id = str(item.get("id") or module_name or item.get("project_link") or "").strip()
    plugin_id = market_id(raw_id)
    if not plugin_id or not is_valid_id(plugin_id):
        return None
    project_link = str(item.get("project_link") or "").strip()
    homepage = str(
        item.get("homepage")
        or item.get("homepage_url")
        or item.get("repository")
        or item.get("repo")
        or ""
    ).strip()
    if not homepage and project_link:
        homepage = project_link if project_link.startswith("https://") else f"https://pypi.org/project/{project_link}/"
    bundle_url = str(
        item.get("bundle_url")
        or item.get("download_url")
        or item.get("release_url")
        or ""
    ).strip()
    if bundle_url and not is_github_url(bundle_url):
        bundle_url = ""
    tags = []
    raw_tags = item.get("tags")
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            if isinstance(tag, dict):
                label = str(tag.get("label") or tag.get("name") or "").strip()
                if label:
                    tags.append({"label": label, "color": str(tag.get("color") or "")})
            else:
                label = str(tag or "").strip()
                if label:
                    tags.append({"label": label, "color": ""})
    author = str(item.get("author") or item.get("author_name") or item.get("author_id") or "")
    description = str(item.get("description") or item.get("desc") or item.get("summary") or "")
    name = str(item.get("name") or module_name or project_link or plugin_id)
    return {
        "id": plugin_id,
        "module_name": module_name,
        "project_link": project_link,
        "name": name,
        "version": str(item.get("version") or ""),
        "description": description,
        "author": author,
        "bundle_url": bundle_url,
        "homepage": homepage,
        "tags": tags,
        "is_official": bool(item.get("is_official", False)),
    }
