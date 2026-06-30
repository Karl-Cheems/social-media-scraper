---
name: skillhub
version: 1.0.0
description: "搜索、查看、下载 SkillHub/ClawHub 技能注册中心（ai.yqsl.xyz）上的远程技能。支持关键词搜索、技能详情浏览、版本列表、文件清单、文件内容查看、版本对比、技能下载。触发词：搜索技能、查看技能、下载技能、skillhub search、skillhub list、远程技能。"
metadata:
  requires:
    bins: ["python3"]
  checks:
    - "python3 -c 'import json, os, urllib.request, urllib.parse, zipfile'"
---

# skillhub — SkillHub 远程技能搜索 & 查看 & 下载

## 适用场景

- 想搜索注册中心上有哪些技能可用（关键词搜索 / 浏览全部）
- 查看某个技能的详细信息（描述、版本、文件清单、下载量、评分）
- 查看技能指定版本包含哪些文件
- 查看技能某个文件的内容（如 SKILL.md、参考脚本）
- 对比两个版本之间的文件差异
- 将远程技能下载到本地使用
- 需要 API Token 来调用需要认证的接口

## 核心流程

```
用户输入搜索词 / 技能标识
  │
  ├─ 搜索:    GET /api/web/skills?q={keyword}
  ├─ 详情:    GET /api/web/skills/{namespace}/{slug}
  ├─ 版本:    GET /api/web/skills/{namespace}/{slug}/versions
  ├─ 文件:    GET .../versions/{version}/files
  ├─ 内容:    GET .../versions/{version}/file?path={path}
  ├─ 对比:    GET .../versions/compare?from={v1}&to={v2}
  └─ 下载:    GET .../download → ZIP → 解压到本地
       │
      输出: 人类可读的信息 / 下载到本地的技能目录
```

## 前置条件

1. **API Token**（可选）：公开技能不需要 token 即可搜索和查看；私有技能需要 token。建议设置环境变量 `SKILLHUB_TOKEN`
2. **注册中心地址**：默认为 `https://ai.yqsl.xyz`，可通过参数覆盖

## 操作说明

以下所有操作使用 Python 脚本 `references/skillhub.py`：

```python
from skillhub import search_skills, get_skill_detail, format_skill_summary
from skillhub import list_versions, format_versions, list_files, format_files
from skillhub import get_file_content, download_skill, compare_versions, format_compare
```

### 1. 搜索技能

```python
# 关键词搜索
data = search_skills('resume', api_token=token)
print(f'共 {data["total"]} 个结果')
for skill in data['items']:
    print(format_skill_summary(skill))

# 浏览全部（按下载量排序）
data = search_skills(sort='downloads', size=50, api_token=token)

# 按命名空间过滤（搜索词加命名空间前缀）
data = search_skills('namespace:tools', api_token=token)
```

### 2. 查看技能详情

```python
skill = get_skill_detail('tools', 'resume-extract', api_token=token)
print(format_skill_summary(skill))
# 输出示例:
#   📦 tools/resume-extract
#   版本: 2.0.0  发布版: 2.0.0  状态: ACTIVE  可见性: PUBLIC
#   下载: 0  ⭐ 0  评分: 0.0 (0人)
#   简介: 从简历压缩包开始，经解压→格式转换...
```

### 3. 查看版本列表

```python
versions = list_versions('tools', 'resume-extract', api_token=token)
print(format_versions(versions))
# 输出示例:
#   ✅ v2.0.0  [PUBLISHED]  3 文件  39KB  2026-05-21
```

### 4. 查看文件清单

```python
files = list_files('tools', 'resume-extract', '2.0.0', api_token=token)
print(format_files(files))
# 输出示例:
#   📄 SKILL.md  (12KB)  text/markdown
#   📄 references/extract_scripts.py  (10KB)  text/x-python
```

### 5. 查看文件内容

```python
content = get_file_content('tools', 'resume-extract', '2.0.0',
                           'SKILL.md', api_token=token)
print(content[:500])  # 打印前 500 字符
```

### 6. 对比版本

```python
diffs = compare_versions('tools', 'resume-extract',
                         '1.0.0', '2.0.0', api_token=token)
print(format_compare(diffs))
```

### 7. 下载技能

```python
# 下载最新版
path = download_skill('tools', 'resume-extract',
                      output_dir='/tmp/skills', api_token=token)

# 下载指定版本
path = download_skill('tools', 'resume-extract', version='2.0.0',
                      output_dir='/tmp/skills', api_token=token)
```

### 一键查看技能（组合操作）

```python
def show_skill(namespace: str, slug: str, api_token: str = ''):
    """一站式查看技能详情 + 版本 + 文件"""
    # 详情
    skill = get_skill_detail(namespace, slug, api_token)
    print(format_skill_summary(skill))

    # 版本
    versions = list_versions(namespace, slug, api_token)
    print('\n版本:')
    print(format_versions(versions[:5]))

    # 最新版本的文件
    latest_ver = skill.get('headlineVersion', {}).get('version', '')
    if latest_ver and versions:
        files = list_files(namespace, slug, latest_ver, api_token)
        print(f'\n文件 ({latest_ver}):')
        print(format_files(files))
```

### CLI 命令行使用

```bash
# 安装依赖（不需要额外依赖，纯标准库）

# 搜索
python3 -c "
from skillhub import search_skills, format_skill_summary
data = search_skills('$1')
for s in data['items']:
    print(format_skill_summary(s))
print(f'共 {data[\"total\"]} 个结果')
"

# 查看详情
python3 -c "
from skillhub import get_skill_detail, format_skill_summary, list_versions, format_versions, list_files, format_files
s = get_skill_detail('$1', '$2')
print(format_skill_summary(s))
vs = list_versions('$1', '$2')
print('\n版本:'); print(format_versions(vs[:5]))
if vs:
    fs = list_files('$1', '$2', vs[0]['version'])
    print('\n文件:'); print(format_files(fs))
"

# 下载
python3 -c "from skillhub import download_skill; download_skill('$1', '$2')"
```

## 输出产物

| 操作 | 输出 |
|------|------|
| 搜索 | 技能列表（命名空间/slug、版本、下载量、评分、简介） |
| 详情 | 技能完整信息（包括所有元数据字段） |
| 版本列表 | 版本号、状态、文件数、大小、创建时间 |
| 文件清单 | 文件路径、大小、MIME 类型 |
| 文件内容 | 原始文件文本内容 |
| 版本对比 | 新增/修改/删除的文件路径列表 |
| 下载 | 解压到本地的技能目录 |

## 注意事项

1. **Token 可选**：搜索和查看公开技能（`PUBLIC` 可见性）不需要 token。查看 `PRIVATE` 或 `NAMESPACE_ONLY` 技能需要 token
2. **分页**：搜索默认每页 20 条，可通过 `size` 参数调整（最大 100）
3. **排序**：支持 `relevance`（相关性）、`downloads`（下载量）、`stars`（星标数）、`newest`（最新）
4. **token 来源**：优先使用函数参数传入的 token，其次读取 `SKILLHUB_TOKEN` 环境变量
5. **下载覆盖**：下载到本地时如果目标目录已存在会直接覆盖，注意备份本地修改