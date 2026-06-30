"""
SkillHub 远程技能查询工具 —— skillhub skill 配套脚本

用法:
  from skillhub import search_skills, get_skill_detail, list_versions, list_files, get_file_content, download_skill
"""

import os
import sys
import json
import urllib.request
import urllib.error
import zipfile
import io


DEFAULT_REGISTRY = 'https://ai.yqsl.xyz'
DEFAULT_TOKEN_ENV = 'SKILLHUB_TOKEN'


def _api_get(path: str, api_token: str = '', registry: str = DEFAULT_REGISTRY) -> dict:
    """通用 GET 请求封装"""
    url = f'{registry.rstrip("/")}{path}'
    req = urllib.request.Request(url)
    if api_token:
        req.add_header('Authorization', f'Bearer {api_token}')

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err = e.read()
        result = json.loads(err) if err else {'code': e.code, 'msg': e.reason}
        raise RuntimeError(f'[{result.get("code")}] {result.get("msg")}')


def _api_get_raw(path: str, api_token: str = '', registry: str = DEFAULT_REGISTRY):
    """GET 请求返回原始 bytes"""
    url = f'{registry.rstrip("/")}{path}'
    req = urllib.request.Request(url)
    if api_token:
        req.add_header('Authorization', f'Bearer {api_token}')
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        err = e.read()
        result = json.loads(err) if err else {'code': e.code, 'msg': e.reason}
        raise RuntimeError(f'[{result.get("code")}] {result.get("msg")}')


# ── 搜索 ──────────────────────────────────────────────────────

def search_skills(
    keyword: str = '',
    sort: str = 'relevance',
    page: int = 0,
    size: int = 20,
    api_token: str = '',
    registry: str = DEFAULT_REGISTRY,
) -> dict:
    """
    搜索技能

    参数:
        keyword: 搜索关键词
        sort:    排序方式（relevance / downloads / stars / newest）
        page:    页码（从 0 开始）
        size:    每页数量

    返回: {"total": N, "items": [...]}
    """
    params = f'q={urllib.parse.quote(keyword)}&sort={sort}&page={page}&size={size}' \
        if keyword else f'sort={sort}&page={page}&size={size}'
    result = _api_get(f'/api/web/skills?{params}', api_token, registry)
    return result['data']


# ── 详情 ──────────────────────────────────────────────────────

def get_skill_detail(
    namespace: str,
    slug: str,
    api_token: str = '',
    registry: str = DEFAULT_REGISTRY,
) -> dict:
    """获取技能详细信息"""
    result = _api_get(f'/api/web/skills/{namespace}/{slug}', api_token, registry)
    return result['data']


def format_skill_summary(skill: dict) -> str:
    """将技能详情格式化为人类可读的摘要"""
    ver = skill.get('headlineVersion') or {}
    pub = skill.get('publishedVersion') or {}
    lines = [
        f'📦 {skill["namespace"]}/{skill["slug"]}',
        f'  版本: {ver.get("version", "N/A")}  '
        f'发布版: {pub.get("version", "N/A")}  '
        f'状态: {skill["status"]}  '
        f'可见性: {skill["visibility"]}',
        f'  下载: {skill.get("downloadCount", 0)}  '
        f'⭐ {skill.get("starCount", 0)}  '
        f'评分: {skill.get("ratingAvg", 0):.1f} ({skill.get("ratingCount", 0)}人)',
    ]
    summary = skill.get('summary', '') or ''
    if summary:
        lines.append(f'  简介: {summary[:120]}')
    return '\n'.join(lines)


# ── 版本列表 ──────────────────────────────────────────────────

def list_versions(
    namespace: str,
    slug: str,
    api_token: str = '',
    registry: str = DEFAULT_REGISTRY,
) -> list:
    """获取技能所有版本"""
    result = _api_get(f'/api/web/skills/{namespace}/{slug}/versions', api_token, registry)
    return result['data'].get('items', result.get('data', []) if isinstance(result.get('data'), list) else [])


def format_versions(versions: list) -> str:
    """格式化版本列表"""
    if not versions:
        return '  (无版本信息)'
    lines = []
    for v in versions:
        status_icon = {'PUBLISHED': '✅', 'PENDING_REVIEW': '⏳', 'REJECTED': '❌', 'DRAFT': '📝'}
        icon = status_icon.get(v['status'], '❓')
        lines.append(f'  {icon} v{v["version"]}  [{v["status"]}]  '
                     f'{v.get("fileCount", "?")} 文件  '
                     f'{_fmt_size(v.get("totalSize", 0))}  '
                     f'{v.get("createdAt", "")[:10]}')
    return '\n'.join(lines)


# ── 文件列表 ──────────────────────────────────────────────────

def list_files(
    namespace: str,
    slug: str,
    version: str,
    api_token: str = '',
    registry: str = DEFAULT_REGISTRY,
) -> list:
    """获取指定版本的文件列表"""
    result = _api_get(
        f'/api/web/skills/{namespace}/{slug}/versions/{version}/files',
        api_token, registry,
    )
    data = result['data'] if isinstance(result, dict) else result
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and 'items' in data:
        return data['items']
    return []


def format_files(files: list) -> str:
    """格式化文件列表为树形结构"""
    if not files:
        return '  (无文件信息)'
    lines = []
    for f in files:
        lines.append(f'  📄 {f["filePath"]}  ({_fmt_size(f["fileSize"])})  '
                     f'{f.get("contentType", "")}')
    return '\n'.join(lines)


# ── 查看文件内容 ──────────────────────────────────────────────

def get_file_content(
    namespace: str,
    slug: str,
    version: str,
    file_path: str,
    api_token: str = '',
    registry: str = DEFAULT_REGISTRY,
) -> str:
    """获取指定文件内容（文本）"""
    raw = _api_get_raw(
        f'/api/web/skills/{namespace}/{slug}/versions/{version}/file?path={urllib.parse.quote(file_path)}',
        api_token, registry,
    )
    return raw.decode('utf-8')


# ── 下载技能 ──────────────────────────────────────────────────

def download_skill(
    namespace: str,
    slug: str,
    output_dir: str = '.',
    version: str = '',
    api_token: str = '',
    registry: str = DEFAULT_REGISTRY,
) -> str:
    """
    下载技能 ZIP 包并解压到 output_dir

    参数:
        namespace:  命名空间
        slug:       技能标识
        output_dir: 解压目标目录
        version:    指定版本（空=latest）
        api_token:  API Token
        registry:   注册中心地址

    返回:
        解压后的目录路径
    """
    path = f'/api/web/skills/{namespace}/{slug}/download'
    if version:
        path += f'?version={urllib.parse.quote(version)}'

    zip_data = _api_get_raw(path, api_token, registry)
    target_dir = os.path.join(output_dir, slug)

    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
        zf.extractall(target_dir)

    file_count = len(zf.namelist())
    print(f'[download] {namespace}/{slug} -> {target_dir} ({file_count} files)')
    return target_dir


# ── 版本对比 ──────────────────────────────────────────────────

def compare_versions(
    namespace: str,
    slug: str,
    from_ver: str,
    to_ver: str,
    api_token: str = '',
    registry: str = DEFAULT_REGISTRY,
) -> list:
    """比较两个版本间的文件差异"""
    path = f'/api/web/skills/{namespace}/{slug}/versions/compare' \
           f'?from={urllib.parse.quote(from_ver)}&to={urllib.parse.quote(to_ver)}'
    result = _api_get(path, api_token, registry)
    data = result['data'] if isinstance(result, dict) else result
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and 'items' in data:
        return data['items']
    return []


def format_compare(diffs: list) -> str:
    """格式化版本对比结果"""
    if not diffs:
        return '  (无差异)'
    lines = []
    for d in diffs:
        if d.get('status') == 'REMOVED':
            lines.append(f'  🗑️  REMOVED  {d["path"]}')
        elif d.get('status') == 'MODIFIED':
            lines.append(f'  ✏️  MODIFIED {d["path"]}')
        elif d.get('status') == 'ADDED':
            lines.append(f'  ➕ ADDED    {d["path"]}')
        else:
            lines.append(f'  ❓ {d.get("status", "?")}  {d["path"]}')
    return '\n'.join(lines)


# ── 工具函数 ──────────────────────────────────────────────────

def _fmt_size(size: int) -> str:
    if size < 1024:
        return f'{size}B'
    elif size < 1024 * 1024:
        return f'{size / 1024:.0f}KB'
    else:
        return f'{size / 1024 / 1024:.1f}MB'


def _get_token(api_token: str = '') -> str:
    return api_token or os.environ.get(DEFAULT_TOKEN_ENV, '')


# 需要导入 urllib.parse
import urllib.parse