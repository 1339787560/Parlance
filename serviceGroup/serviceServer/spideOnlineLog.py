import argparse
import datetime as dt
from errno import EROFS
from fileinput import filename
from itertools import count
import os
import sys
import time
import re
import json
from typing import List

import requests

# 修正正则表达式以匹配带方括号的时间戳（如[08:52:55.727]）
_TIMESTAMP_RE = re.compile(r'^\[\d{2}:\d{2}:\d{2}\.\d{3}\]')


def _parse_dates(args_dates: List[str]) -> List[dt.date]:
    """
    解析输入的日期参数，返回 [start_date, end_date]
    - 不传：今天 -> 今天
    - 传 1 个：start -> 今天
    - 传 2 个：start -> end
    """
    today = dt.date.today()

    if len(args_dates) == 0:
        start_date, end_date = today, today
    elif len(args_dates) == 1:
        start_date = _str_to_date(args_dates[0])
        end_date = today
    elif len(args_dates) == 2:
        start_date = _str_to_date(args_dates[0])
        end_date = _str_to_date(args_dates[1])
    else:
        raise ValueError("最多只能传入两个日期参数，格式示例：2025-11-18 2025-11-19")

    # 确保 start <= end
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    return [start_date, end_date]


def _str_to_date(s: str) -> dt.date:
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"日期格式错误：{s}，请使用 YYYY-MM-DD，例如 2025-11-18")


def _date_range(start: dt.date, end: dt.date) -> List[dt.date]:
    days = (end - start).days
    return [start + dt.timedelta(days=i) for i in range(days + 1)]


def _ensure_output_dir() -> str:
    """
    输出目录固定为项目中的 tmp/html（绝对路径）
    d:\\study\\python\\errorCheck\\tmp\\html
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_dir = os.path.join(project_root, "tmp", "html")
    # 若路径存在但为文件，则切换到 tmp/html_output 目录
    if os.path.exists(out_dir):
        if os.path.isfile(out_dir):
            alt_dir = os.path.join(project_root, "tmp", "html_output")
            os.makedirs(alt_dir, exist_ok=True)
            return alt_dir
        return out_dir
    # 路径不存在则创建目录
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def _build_url(d: dt.date, project: str = "zgda") -> str:
    # 目标目录页： http://logdebug.tcy365.org:2505/upload/{project}/YYYYMMDD/
    return f"http://logdebug.tcy365.org:2505/upload/{project}/{d.strftime('%Y%m%d')}/"


def _fetch_html(url: str, session: requests.Session, timeout: int = 15, retries: int = 3) -> str:
    """
    拉取目录页 HTML，带简单重试
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/5.0 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers=headers, timeout=timeout)
            # 某些服务器不会正确声明编码，这里根据响应猜测编码
            resp.encoding = resp.apparent_encoding or "utf-8"
            if resp.status_code == 200:
                return resp.text
            else:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
        except requests.RequestException as e:
            last_exc = e

        # 简单退避
        time.sleep(min(2 * attempt, 5))

    if last_exc:
        raise RuntimeError(f"获取失败：{url}，错误：{last_exc}")
    raise RuntimeError(f"获取失败：{url}，未知错误")


def _save_html(content: str, out_dir: str, d: dt.date) -> str:
    """
    保存为 index_YYYYMMDD.html
    """
    fname = f"index_{d.strftime('%Y%m%d')}.html"
    out_path = os.path.join(out_dir, fname)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    return out_path


def _extract_file_links(html: str) -> List[str]:
    """
    从目录页 HTML 中提取所有 .txt 文件链接（href），排除 '../'
    适配 Apache/Nginx 的目录索引页，支持单/双引号与多属性
    """
    import re
    # 支持多属性、单双引号、大小写不敏感
    pattern = re.compile(r'<a[^>]*\s+href=["\']([^"\']+)["\']', re.IGNORECASE)
    hrefs = pattern.findall(html)

    results = []
    for h in hrefs:
        if not h:
            continue
        h = h.strip()
        if h in ("", "../"):
            continue
        if h.lower().endswith(".txt"):
            results.append(h)
    return results


def _ensure_date_subdir(out_dir: str, d: dt.date) -> str:
    """
    在输出目录下为当天创建子目录：YYYYMMDD
    """
    subdir = os.path.join(out_dir, d.strftime("%Y%m%d"))
    os.makedirs(subdir, exist_ok=True)
    return subdir


def _download_file(file_url: str, dest_path: str, session: requests.Session, timeout: int = 20, retries: int = 3, force: bool = False) -> None:
    """
    下载单个文件到 dest_path，若已存在则跳过；带简单重试
    """
    if not force and os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        print(f"  [跳过] 已存在：{dest_path}")
        return

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            with session.get(file_url, headers=headers, timeout=timeout, stream=True) as resp:
                if resp.status_code != 200:
                    last_exc = RuntimeError(f"HTTP {resp.status_code}")
                    raise last_exc
                tmp_path = dest_path + ".part"
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                os.replace(tmp_path, dest_path)
                return
        except requests.RequestException as e:
            last_exc = e
        except Exception as e:
            last_exc = e

        time.sleep(min(2 * attempt, 5))

    if last_exc:
        raise RuntimeError(f"下载失败：{file_url} -> {dest_path}，错误：{last_exc}")


# 顶层新增函数
def _read_text_file(path: str) -> str:
    """
    读取文本文件，尝试多种编码回退
    """
    for enc in ("utf-8", "gb18030", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return f.read()
        except Exception:
            continue
    # 最后兜底，忽略错误
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _fetch_text(file_url: str, session: requests.Session, timeout: int = 20) -> str:
    """
    在线获取文本内容（不落盘），带编码猜测
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    resp = session.get(file_url, headers=headers, timeout=timeout)
    resp.encoding = resp.apparent_encoding or "utf-8"
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.text


def _extract_matches(text: str, regex: str, ignore_case: bool = False, block: bool = False, max_matches: int = None) -> list:
    """
    使用用户提供的正则，在文本中筛选匹配的整行或整段，返回 [(line_no, line_text_or_block)]
    当 block=True 时，开启跨行块匹配（DOTALL），返回每个匹配块的起始行号与整段文本。
    max_matches 非 None 时, 截断到前 N 条 (OSS 日志单文件可达百万行, 避免输出爆炸)。
    """
    import re
    if block:
        flags = (re.IGNORECASE if ignore_case else 0) | re.DOTALL | re.MULTILINE
        pattern = re.compile(regex, flags)
        results = []
        for m in pattern.finditer(text):
            start_pos = m.start()
            line_no = text.count("\n", 0, start_pos) + 1
            matched_text = m.group(0)
            results.append((line_no, matched_text))
            if max_matches is not None and len(results) >= max_matches:
                break
        return results
    flags = re.IGNORECASE if ignore_case else 0
    pattern = re.compile(regex, flags)
    lines = text.splitlines()
    results = []
    for idx, line in enumerate(lines, start=1):
        if pattern.search(line):
            results.append((idx, line))
            if max_matches is not None and len(results) >= max_matches:
                break
    return results


def _write_extract_summary(date_dir: str, d: dt.date, per_file_matches: dict, project: str) -> str:
    """
    把当日的提取结果写入 extract_YYYYMMDD.txt，包含远程URL、本地路径（若有）和行号
    per_file_matches 结构：
      {
        file_name: {
          "url": <remote url>,
          "local": <local path or None>,
          "matches": [(line_no, line_text), ...]
        },
        ...
      }
    """
    out_path = os.path.join(date_dir, f"aa_extract_{project}_{d.strftime('%Y%m%d')}.txt")
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        for fname, info in per_file_matches.items():
            url = info.get("url") or ""
            local = info.get("local") or ""
            matches = info.get("matches") or []

            if not matches:
                continue

            f.write(f"==== {fname} ====\n")
            if url:
                f.write(f"URL: {url}\n")
            if local:
                f.write(f"LOCAL: {local}\n")

            if matches:
                for ln, line in matches:
                    f.write(f"[L{ln}] {line}\n")
            else:
                f.write("(no matches)\n")
            f.write("\n")
    return out_path

def _format_extract_summary_data(per_file_matches: dict):
    matched_count = 0
    errorMap = {}
    for fname, info in per_file_matches.items():
        matches = info.get("matches") or []
        if not matches:
            continue

        for ln, line in matches:
            key = remove_timestamp_from_first_line(line)
            errors = errorMap.get(key, {})
            files = errors.get("files", [])
            files.append({'url': info.get("url") or "", 'filename': fname, 'line':ln, 'errmsg':line})
            errors['files'] = files
            errors['count'] = errors.get('count', 0) + 1
            errorMap[key] = errors
            matched_count += 1
    return matched_count, errorMap
def generate_html_report(project:str, matched_count: int, errorMap: dict, start_date='0', end_date='0') -> str:
    if matched_count == 0:
        return "<p>没有匹配到任何错误信息。</p>"

    # 按 count 降序排序
    sorted_errors = sorted(
        errorMap.items(),
        key=lambda item: item[1]["count"],
        reverse=True
    )

    html_parts = [
        '<html>',
        '<head>',
        '<meta charset="utf-8">',
        '<title>' + project + '错误汇总报表</title>',
        '<style>',
        'body { font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; background: #fff; }',
        'pre { white-space: pre-wrap; word-break: break-word; }',
        '.error-block { margin-bottom: 2em; padding: 1em; border: 1px solid #ddd; border-radius: 6px; background: #fafafa; }',
        'details { margin-top: 10px; }',
        'summary { cursor: pointer; font-weight: bold; color: #1a73e8; outline: none; }',
        'summary:hover { text-decoration: underline; }',
        'ul { margin-top: 8px; padding-left: 20px; }',
        'li { margin: 4px 0; }',
        '</style>',
        '</head>',
        '<body>'
    ]
    
    html_parts.append(f"<h2>项目：{project} 范围：{start_date} -> {end_date} === 总计匹配行数: {matched_count}</h2>")

    html_parts.append("<hr>")

    for key, info in sorted_errors:
        count = info["count"]
        ratio = count / matched_count * 100
        files = info["files"]

        html_parts.append('<div class="error-block">')
        html_parts.append(f"<p><strong>出现次数：</strong>{count} &nbsp;&nbsp; <strong>占比：</strong>{ratio:.2f}%</p>")
        html_parts.append(f"<pre style='background:#f4f4f4;padding:10px;border-radius:4px;'>{key}</pre>")

        # 原始 errmsg（取第一个）
        first_errmsg = files[0]["errmsg"]
        html_parts.append(f"<pre style='background:#ffebee;padding:10px;border-radius:4px;color:#c62828;'>{first_errmsg}</pre>")

        # 折叠的“关联文件”区域
        html_parts.append('<details>')
        html_parts.append('<summary>关联文件（点击展开）</summary>')
        html_parts.append('<ul>')
        for f in files:
            line_num = f['line']
            url = f['url']
            filename = f['filename']
            display_name = url if url else filename
            if url:
                link = f'<a href="{url}" target="_blank" rel="noopener">{display_name}</a>'
            else:
                link = display_name
            html_parts.append(f"<li><strong>[{line_num}]</strong> {link}</li>")
        html_parts.append('</ul>')
        html_parts.append('</details>')

        html_parts.append('</div>')
        html_parts.append("<hr>")

    html_parts.append("</body></html>")
    return "".join(html_parts)

def _write_extract_summary_htmlV2(date_dir: str, d: dt.date, per_file_matches: dict, project: str, start_date, end_date) -> str:
    """
    生成 HTML 汇总 extract_YYYYMMDD.html，仅包含有匹配结果的文件（过滤掉 no matches），并显示匹配文件总数
    """
    out_path = os.path.join(date_dir, f"aa_extract_{project}_{d.strftime('%Y%m%d')}.html")
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        matched_count, errorMap = _format_extract_summary_data(per_file_matches)
        html_report = generate_html_report(project, matched_count, errorMap, start_date, end_date)
        f.write(html_report)
    return out_path

def remove_timestamp_from_first_line(text: str) -> str:
    # 快速找到第一个换行符位置（不生成所有行）
    newline_pos = text.find('\n')
    first_line = text if newline_pos == -1 else text[:newline_pos]

    # 应用预编译的正则替换
    return _TIMESTAMP_RE.sub('', first_line, count=1)

# ==================== OSS 源 (tcgamelog) ====================
# 路径约定: {service}/{hostID}/{log|Record}/{service}-{YYYYMMDD}{HHMMSS}-{log|Record}.zip
# zip 单层, 内含多个 GBK 编码 .log。凭据走 CredsManager.get_oss_creds (db_creds.enc['oss'])。
# 注册表 oss_hosts.yaml 记录 hostID→service 反查 (hostID 跨 service 复用, 勿臆断)。

def _oss_svc_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'CommonTools', 'xzmpDB')


def _oss_connect():
    """构造 oss2.Bucket。延迟 import, HTTP 源不依赖 oss2。"""
    import sys
    if _oss_svc_dir() not in sys.path:
        sys.path.insert(0, _oss_svc_dir())
    from CredsManager import get_oss_creds
    import oss2
    c = get_oss_creds()
    auth = oss2.Auth(c['access_key_id'], c['access_key_secret'])
    return oss2.Bucket(auth, c['endpoint'], c['bucket'])


def _oss_load_hosts() -> dict:
    import yaml
    path = os.path.join(_oss_svc_dir(), 'oss_hosts.yaml')
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def _oss_resolve_service_host(service_arg: str, host_arg: str):
    """service 缺省 → 注册表反查。返回 (service, host)。"""
    if service_arg:
        return service_arg, host_arg
    if not host_arg:
        raise ValueError("OSS 源需要 --service 或注册表中登记的 --host")
    registry = _oss_load_hosts()
    for svc, hosts in registry.items():
        if isinstance(hosts, dict) and any(str(k) == str(host_arg) for k in hosts):
            return svc, host_arg
    raise ValueError(f"host {host_arg} 未在 oss_hosts.yaml 登记; 请显式传 --service")


def _oss_list_date_files(bucket, service: str, host: str, date_str: str, subdir: str = 'log') -> list:
    """列 {service}/{host}/{subdir}/{service}-{date}*-log.zip。返回 [(key, basename)]。"""
    import oss2
    import re
    prefix = f"{service}/{host}/{subdir}/"
    pat = re.compile(
        r'^' + re.escape(prefix) + re.escape(service) + r'-' + date_str + r'\d{6}-' + re.escape(subdir) + r'\.zip$'
    )
    files = []
    for o in oss2.ObjectIterator(bucket, prefix=prefix, max_keys=1000):
        if pat.match(o.key):
            files.append((o.key, os.path.basename(o.key)))
    files.sort()
    return files


def _decode_bytes(raw: bytes) -> str:
    """多编码回退 (与 _read_text_file 一致)。OSS 日志多为 GBK。"""
    for enc in ('utf-8', 'gb18030', 'gbk', 'latin-1'):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode('utf-8', errors='ignore')


def _oss_zip_extract_text(bucket, key: str, log_name_regex: str = None) -> str:
    """下载 zip 到内存, 解压匹配 .log, GBK 解码拼接。log_name_regex 过滤内层文件名。"""
    import io
    import re
    import zipfile
    data = bucket.get_object(key).read()
    zf = zipfile.ZipFile(io.BytesIO(data))
    pat = re.compile(log_name_regex) if log_name_regex else None
    parts = []
    for name in zf.namelist():
        if not name.lower().endswith('.log'):
            continue
        if pat and not pat.search(name):
            continue
        parts.append(_decode_bytes(zf.read(name)))
    return "\n".join(parts)


def _oss_download_zip(bucket, key: str, dest_dir: str) -> str:
    dest = os.path.join(dest_dir, os.path.basename(key))
    data = bucket.get_object(key).read()
    with open(dest, 'wb') as f:
        f.write(data)
    return dest


def _oss_list_record_files(bucket, service: str, host: str, date_str: str) -> list:
    """列 {service}/{host}/Record/{date}*.zip 内层 `game/{service}/Record/{tableNO}_{date}.log`
    作 record 索引项。每日一 zip, 内含多对局 .log (复盘器按对局选, 非 zip 粒度)。
    返 [{key, zip_key, inner, table_no, date, size}]。key = zip_key + '::' + inner (供 --fetch 定位)。
    依赖 _oss_list_date_files 正则已参数化 subdir (匹配 `-Record.zip`)。"""
    import io
    import re
    import zipfile
    zips = _oss_list_date_files(bucket, service, host, date_str, subdir='Record')
    inner_re = re.compile(rf'game/{re.escape(service)}/Record/(\d+)_(\d{{8}})\.log$')
    items = []
    for zip_key, _display in zips:
        data = bucket.get_object(zip_key).read()
        zf = zipfile.ZipFile(io.BytesIO(data))
        for info in zf.infolist():
            m = inner_re.match(info.filename)
            if not m:
                continue
            items.append({
                'key': f'{zip_key}::{info.filename}',
                'zip_key': zip_key,
                'inner': info.filename,
                'table_no': m.group(1),
                'date': m.group(2),
                'size': info.file_size,
            })
    items.sort(key=lambda x: (x['date'], x['table_no']))
    return items


def _oss_fetch_record_file(bucket, key: str) -> bytes:
    """key = '{zip_key}::{inner}' → 下载 zip, 取 inner 单 record .log 原始字节 (GBK,
    不 Python 解码; 交调用方 Rust crate::encoding::decode 统一处理, 与 local 源一致)。"""
    import io
    import zipfile
    zip_key, inner = key.split('::', 1)
    data = bucket.get_object(zip_key).read()
    zf = zipfile.ZipFile(io.BytesIO(data))
    return zf.read(inner)


def _ensure_oss_output_dir(service: str, host: str) -> str:
    project_root = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(project_root, 'tmp', 'oss_html', f"{service}_{host}")
    os.makedirs(out, exist_ok=True)
    return out


def _run_oss_source(args, dates: list):
    """OSS 源主流程, 镜像 HTTP 源: 列 zip → 解压 grep → HTML 汇总。
    分流: --fetch 取单 record 文本 / --json list 返 JSON 索引 (record 子目录按内层 .log 分条) / 默认 HTML 报告。"""
    bucket = _oss_connect()

    # --fetch 最先: key = zip_key::inner 已含定位, 不需 --service/--host (复盘器 get 用)
    if args.fetch:
        sys.stdout.buffer.write(_oss_fetch_record_file(bucket, args.fetch))
        return

    service, host = _oss_resolve_service_host(args.service, args.host)

    # --json: list 返 JSON 索引 (Record 子目录按 zip 内层 .log 分条, 非 zip 粒度; 复盘器 list 用)
    if args.json:
        items = []
        for d in dates:
            items.extend(_oss_list_record_files(bucket, service, host, d.strftime('%Y%m%d')))
        sys.stdout.write(json.dumps(items, ensure_ascii=False))
        return

    out_dir = _ensure_oss_output_dir(service, host)
    bucket_name = bucket.bucket_name
    project_label = f"{service}_{host}"

    print(f"[OSS] endpoint={get_oss_endpoint(bucket)} bucket={bucket_name}")
    print(f"[OSS] service={service} host={host} subdir={args.subdir} log_name={args.log_name or '(全部 .log)'}")
    print(f"输出目录：{out_dir}")
    print(f"抓取日期范围：{dates[0]} -> {dates[-1]}（共 {len(dates)} 天）")

    limit = args.limit if (args.limit is not None and args.limit > 0) else None
    processed_total = 0
    success = 0
    failures = []

    for d in dates:
        date_str = d.strftime('%Y%m%d')
        try:
            files = _oss_list_date_files(bucket, service, host, date_str, args.subdir)
            print(f"\n[{date_str}] 命中 {len(files)} 个 zip")
            if not files:
                success += 1
                continue

            date_dir = _ensure_date_subdir(out_dir, d)
            per_file_matches = {}

            for key, display in files:
                if limit is not None and processed_total >= limit:
                    print(f"已达上限（{limit} 条），停止当日处理")
                    break
                try:
                    local_zip = None
                    if args.download:
                        local_zip = _oss_download_zip(bucket, key, date_dir)
                        print(f"  [完成] 下载 {display}")
                    text = _oss_zip_extract_text(bucket, key, args.log_name)
                    processed_total += 1
                    if args.regex:
                        matches = _extract_matches(text, args.regex, args.ignore_case, args.block, args.max_matches)
                        per_file_matches[display] = {
                            "url": f"oss://{bucket_name}/{key}",
                            "local": local_zip,
                            "matches": matches,
                        }
                    else:
                        print(f"  [提示] 无 --regex, {display} 解压后未解析")
                except Exception as e:
                    print(f"  [失败] {display} -> {e}")
                    per_file_matches[display] = {
                        "url": f"oss://{bucket_name}/{key}",
                        "local": None,
                        "matches": [],
                    }

            if args.regex:
                has_any = any((info.get("matches") or []) for info in per_file_matches.values())
                if has_any:
                    summary_txt = _write_extract_summary(date_dir, d, per_file_matches, project_label)
                    summary_html = _write_extract_summary_htmlV2(
                        date_dir, d, per_file_matches, project_label, dates[0], dates[-1]
                    )
                    print(f"提取结果汇总：{summary_txt}")
                    print(f"提取结果汇总(HTML)：{summary_html}")
                else:
                    print("本次没有任何匹配，未生成汇总文件")
            success += 1
            if limit is not None and processed_total >= limit:
                print(f"已达总上限（{limit} 条），停止后续日期")
                break
        except Exception as e:
            print(f"[失败] {date_str} -> {e}")
            failures.append((d, str(e)))

    print("\n=== 汇总 ===")
    print(f"成功：{success}，失败：{len(failures)}")
    if failures:
        for d, err in failures:
            print(f"  {d}: {err}")


def get_oss_endpoint(bucket) -> str:
    # oss2 Bucket 暴露 endpoint
    try:
        return getattr(bucket, 'endpoint', '')
    except Exception:
        return ''


def main():
    # 参数定义与解析
    parser = argparse.ArgumentParser(
        description="抓取 http://logdebug.tcy365.org:2505/upload/{project}/YYYYMMDD/ 目录页 HTML 到 tmp/html",
        epilog=(
            "用法示例：\n"
            "  python src/main.py                                # 抓取今天（默认项目 zgda，下载并解析）\n"
            "  python src/main.py -p zgda 2025-11-18             # 指定项目，抓取 2025-11-18 到今天\n"
            "  python src/main.py -p zgda 2025-11-18 2025-11-19  # 指定项目，抓取两天\n"
            "  python src/main.py -r \"UR_SOCKET_CONNECT\"        # 指定正则提取匹配行\n"
            "  python src/main.py -r \"ERROR|FAIL\" -i            # 忽略大小写\n"
            "  python src/main.py --no-download -r \"KICKOFF\"    # 仅在线解析，不保存文件\n"
            "  python src/main.py -n 100                         # 本次最多获取 100 条文件\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    # 允许传入 0-2 个位置参数作为日期
    parser.add_argument("--project", "-p", default="zgda", help="项目名称，默认：zgda")
    parser.add_argument("--regex", "-r", default=None, help="用于匹配的正则表达式（例如：UR_SOCKET_CONNECT|UR_DATABASE_ERROR）")
    parser.add_argument("--ignore-case", "-i", action="store_true", help="提取时忽略大小写")
    parser.add_argument("--download", dest="download", action="store_true", default=True, help="是否将文件保存到本地，默认保存")
    parser.add_argument("--no-download", dest="download", action="store_false", help="不保存到本地，仅在线解析")
    parser.add_argument("--force-latest", "--force", dest="force_latest", action="store_true", help="是否强制使用最新文件（忽略本地缓存），默认关闭")
    parser.add_argument("--limit", "-n", type=int, default=None, help="总获取条数上限（文件级），默认不限制")
    parser.add_argument("--max-matches", type=int, default=None, help="单文件匹配行数上限 (OSS 大日志防输出爆炸; 默认不限)")
    parser.add_argument("--verbose", "-v", action="store_true", help="开启详细日志输出")
    parser.add_argument("--block", action="store_true", help="按多行块匹配（跨行匹配整个片段）")
    # OSS 源参数 (tcgamelog)
    parser.add_argument("--source", choices=["http", "oss"], default="http", help="日志源: http(logdebug.tcy365) | oss(tcgamelog)")
    parser.add_argument("--service", default=None, help="[OSS] service 前缀, 如 roomsvrxzms / xzmochunklog")
    parser.add_argument("--host", default=None, help="[OSS] hostID, 如 3291; 注册表内可省 --service")
    parser.add_argument("--subdir", default="log", help="[OSS] 子目录: log | Record (默认 log)")
    parser.add_argument("--log-name", default=None, help="[OSS] zip 内 .log 文件名正则过滤 (默认全部 .log)")
    parser.add_argument("--json", action="store_true", help="[OSS] list 返 JSON 索引 (stdout 纯 JSON, 不产 HTML; 配 --subdir Record 取对局牌谱索引, 按内层 .log 分条)")
    parser.add_argument("--fetch", default=None, help="[OSS] 取单 record 文本 (key = --json list 返的 key; 配 --subdir Record)")
    parser.add_argument("dates", nargs="*", help="日期参数（0-2 个），格式：YYYY-MM-DD")
    args = parser.parse_args()
    if not (args.json or args.fetch):
        print("参数：",args)

    try:
        start_date, end_date = _parse_dates(args.dates)
    except ValueError as e:
        print(f"[参数错误] {e}", file=sys.stderr)
        sys.exit(2)

    out_dir = _ensure_output_dir()
    dates = _date_range(start_date, end_date)

    if args.source == "oss":
        _run_oss_source(args, dates)
        return

    print(f"输出目录：{out_dir}")
    print(f"抓取日期范围：{start_date} -> {end_date}（共 {len(dates)} 天）")

    session = requests.Session()
    success = 0
    failures = []

    # 总获取条数控制
    processed_total = 0
    limit = args.limit if (args.limit is not None and args.limit > 0) else None

    for d in dates:
        url = _build_url(d, args.project)
        print(f"正在抓取：{url} ...")
        try:
            html = _fetch_html(url, session=session)
            saved_path = _save_html(html, out_dir, d)
            print(f"保存完成：{saved_path}")

            # 解析并下载/解析文件
            file_links = _extract_file_links(html)
            if args.verbose:
                print(f"[DEBUG] 提取到链接数量：{len(file_links)}")
            if file_links:
                date_dir = _ensure_date_subdir(out_dir, d)
                if args.verbose:
                    print(f"[DEBUG] 将处理并{('下载' if args.download else '解析')}到：{date_dir}")
                    for i, h in enumerate(file_links[:5], 1):
                        print(f"[DEBUG] 示例链接 {i}: {h}")

                per_file_matches = {}

                for href in file_links:
                    # 上限控制
                    if limit is not None and processed_total >= limit:
                        print(f"已达到限制（{limit} 条），停止当日文件处理")
                        break

                    file_url = url + href
                    file_name = os.path.basename(href)
                    dest_path = os.path.join(date_dir, file_name)
                    if args.verbose:
                        print(f"[DEBUG] 准备处理：{file_url} -> {dest_path} (download={args.download}, force={args.force_latest})")

                    try:
                        if args.download:
                            _download_file(file_url, dest_path, session=session, force=args.force_latest)
                            print(f"  [完成] 下载 {file_name}")
                            processed_total += 1
                            if args.regex:
                                text = _read_text_file(dest_path)
                                matches = _extract_matches(text, args.regex, args.ignore_case, args.block, args.max_matches)
                                per_file_matches[file_name] = {"url": file_url, "local": dest_path, "matches": matches}
                        else:
                            if args.regex:
                                text = _fetch_text(file_url, session=session)
                                matches = _extract_matches(text, args.regex, args.ignore_case, args.block, args.max_matches)
                                per_file_matches[file_name] = {"url": file_url, "local": None, "matches": matches}
                                processed_total += 1
                            else:
                                print(f"  [提示] 未提供 --regex，已跳过 {file_name} 的在线解析（不计入限额）")
                    except Exception as e:
                        print(f"  [失败] {file_name} -> {e}")
                        per_file_matches[file_name] = {"url": file_url, "local": (dest_path if args.download else None), "matches": []}

                # 写入当日提取汇总（文本与HTML）
                if args.regex:
                    # 只有当存在至少一条匹配时才写入汇总文件
                    has_any_match = any((info.get("matches") or []) for info in per_file_matches.values())
                    if has_any_match:
                        summary_txt = _write_extract_summary(date_dir, d, per_file_matches, args.project)
                        summary_html = _write_extract_summary_htmlV2(date_dir, d, per_file_matches, args.project, start_date, end_date)
                        print(f"提取结果汇总：{summary_txt}")
                        print(f"提取结果汇总(HTML)：{summary_html}")
                    else:
                        print("本次没有任何匹配，未生成汇总文件")
                else:
                    print("未提供 --regex，跳过提取汇总写入")
            else:
                print("未发现 .txt 文件链接")

            success += 1
        except Exception as e:
            print(f"[失败] {url} -> {e}")

            failures.append((d, str(e)))
    print("\n=== 汇总 ===")
    print(f"成功：{success}，失败：{len(failures)}")
    if failures:
        for d, err in failures:
            print(f"  {d}: {err}")


if __name__ == "__main__":
    main()