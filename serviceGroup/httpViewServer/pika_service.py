# -*- coding: utf-8 -*-
"""
pika（哔咔漫画 picacomic）源服务模块。

依托 picacg-qt 逆向调研（见 SDD 调研报告）自实现，仅依赖 requests：
- API 签名: HMAC-SHA256(secret, (path+time+nonce+method+apiKey).lower())
- 登录: POST auth/sign-in → token（无刷新机制, 401 自动重登）
- 图片无需解密: fileServer + "/static/" + path 明文直下（带 authorization + Host 头）
- 凭据: pika_config.json（服务 cwd 下 {email, password}）

复用 jm_service 的通用文件助手（temp/persist 结构、aid 反查、回收等）。
"""
import os
import re
import json
import time
import uuid
import hmac
import hashlib
import threading
import requests

from const import SHARE_DIR
from jm_service import (
    _sanitize, _merge_move, _has_real_images, _touch_last_read,
    _find_album_dir_by_aid, _write_aid, _count_images,
    _config_get, _config_set,
    ONLINE_META_FILE, LAST_READ_FILE, AID_FILE,
)

# ===== 常量（picacg-qt 硬编码, 全网公开） =====
API_BASE = 'https://picaapi.picacomic.com/'
API_KEY = 'C69BAF41DA5ABD1FFEDC6D2FEA56B'
SECRET_KEY = '~d}$Q7$eIni=V)9\\RK/P.RM4;9[7|@/CA}b~OW!3?EV`:<>M7pddUBL5n|0/*Cn'
FIXED_HEADERS = {
    'api-key': API_KEY,
    'accept': 'application/vnd.picacomic.com.v1+json',
    'app-channel': '3',
    'app-version': '2.2.1.3.3.4',
    'app-uuid': 'defaultUuid',
    'image-quality': 'original',
    'app-platform': 'android',
    'app-build-version': '45',
    'user-agent': 'okhttp/3.8.1',
    'version': 'v1.5.4',
}
# 图片备用域名切换表（404/403 时替换 host）
IMG_FALLBACK_HOSTS = ['storage-b.picacomic.com', 's3.picacomic.com',
                      'storage1.picacomic.com', 'storage.picacomic.com',
                      'img.picacomic.com']
# tobeimg 封面跳转域（picacg-qt req.py jumpDomain）
IMG_JUMP_DOMAINS = {
    'storage-b.picacomic.com': 'img.picacomic.com',
    's3.picacomic.com': 'img.picacomic.com',
    'storage1.picacomic.com': 'img.picacomic.com',
    'storage.picacomic.com': 'img.picacomic.com',
}

CONFIG_FILE = os.path.join(os.path.abspath('.'), 'pika_config.json')
COVER_CACHE_DIR = os.path.join(os.path.abspath('.'), 'pika_cover_cache')
API_PAGE_SIZE = 20  # pika API 单页条数

_token = None
_token_lock = threading.Lock()


# ===== 配置 =====

def _load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(email, password):
    """保存 pika 凭据到 pika_config.json。"""
    cfg = _load_config()
    if email is not None:
        cfg['email'] = str(email).strip()
    if password is not None:
        cfg['password'] = str(password)
    tmp = CONFIG_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)
    global _token
    with _token_lock:
        _token = None  # 凭据变更后强制重登
    return True


def get_config():
    cfg = _load_config()
    return {'email_set': bool(cfg.get('email'))}


# ===== 签名与请求 =====

def _sign(path, method):
    """生成 time/nonce/signature 三件套。path 不含域名且无前导斜杠（如 auth/sign-in）。"""
    path = path.lstrip('/')
    now = str(int(time.time()))
    nonce = str(uuid.uuid1()).replace('-', '')
    src = path + now + nonce + method + API_KEY
    sig = hmac.new(SECRET_KEY.encode('utf-8'), src.lower().encode('utf-8'),
                   hashlib.sha256).hexdigest()
    return now, nonce, sig


def _headers(path, method, auth=True):
    now, nonce, sig = _sign(path, method)
    h = dict(FIXED_HEADERS)
    h.update({'time': now, 'nonce': nonce, 'signature': sig})
    if auth:
        token = _get_token()
        if token:
            h['authorization'] = token
    return h


def _get_token():
    with _token_lock:
        if _token:
            return _token
    return _login()


def _login():
    """登录取 token（无刷新机制, 401 时重登）。"""
    cfg = _load_config()
    if not cfg.get('email') or not cfg.get('password'):
        raise RuntimeError('pika 未配置账号（请在 pika_config.json 填写 email/password）')
    path = '/auth/sign-in'
    headers = _headers(path, 'POST', auth=False)
    headers['Content-Type'] = 'application/json; charset=UTF-8'
    resp = requests.post(API_BASE + path.lstrip('/'),
                         json={'email': cfg['email'], 'password': cfg['password']},
                         headers=headers, timeout=20)
    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f'pika 登录响应异常: HTTP {resp.status_code}')
    if data.get('code') == 200 and data.get('data', {}).get('token'):
        tok = data['data']['token']
        with _token_lock:
            global _token
            _token = tok
        return tok
    raise RuntimeError(f'pika 登录失败: {data.get("message", resp.status_code)}')


def _api(method, path, params=None, body=None, auth=True):
    """带签名+token 的 API 请求, 401 自动重登重试一次。返回 data 段。
    签名基于完整路径(含查询串), 与 picacg-qt GetHeader / PicaComic createSignature 一致。"""
    url = API_BASE + path.lstrip('/')
    if params:
        qs = '&'.join(f'{k}={requests.utils.quote(str(v))}' for k, v in params.items())
        url = url + '?' + qs
    sign_path = url[len(API_BASE):]  # 含查询串, 无域名
    for attempt in range(2):
        headers = _headers(sign_path, method, auth=auth)
        if body is not None:
            headers['Content-Type'] = 'application/json; charset=UTF-8'
        resp = requests.request(method, url, json=body, headers=headers, timeout=20)
        if resp.status_code == 401 and attempt == 0:
            with _token_lock:
                global _token
                _token = None
            continue
        try:
            data = resp.json()
        except Exception:
            raise RuntimeError(f'pika API 响应异常: HTTP {resp.status_code}')
        if data.get('code') != 200:
            raise RuntimeError(f'pika API 错误: {data.get("message", resp.status_code)}')
        return data.get('data', {})
    raise RuntimeError('pika API 401 重试失败')


def _img_headers(file_server, method='Download'):
    """图片请求头: 签名(method=Download) + authorization + Host。"""
    path = '/static/'
    now, nonce, sig = _sign(path, method)
    h = dict(FIXED_HEADERS)
    h.update({'time': now, 'nonce': nonce, 'signature': sig,
              'Host': file_server.replace('https://', '').replace('http://', '').rstrip('/')})
    token = _get_token()
    if token:
        h['authorization'] = token
    return h


def _fetch_image(url, file_server, dest):
    """下载图片（带鉴权+Host, 404/403 切备用域名重试）。"""
    headers = _img_headers(file_server)
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code in (404, 403):
        # 切备用域名重试
        for host in IMG_FALLBACK_HOSTS:
            alt_url = url.replace(file_server, f'https://{host}')
            alt_headers = _img_headers(f'https://{host}')
            alt = requests.get(alt_url, headers=alt_headers, timeout=30)
            if alt.status_code == 200:
                resp = alt
                break
    if resp.status_code != 200:
        raise RuntimeError(f'图片下载失败: HTTP {resp.status_code}')
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'wb') as f:
        f.write(resp.content)
    return dest


# ===== 数据获取 =====

def album_detail(book_id):
    """漫画详情: {id, title, author, thumb, eps:[{id,title,order}]}（eps 按 order 升序）。"""
    data = _api('GET', f'/comics/{book_id}')
    comic = data.get('comic', {})
    eps = []
    page = 1
    while True:
        eps_data = _api('GET', f'/comics/{book_id}/eps', params={'page': page})
        eps_list = eps_data.get('eps', {}).get('docs', [])
        for e in eps_list:
            eps.append({'id': e.get('id', ''), 'title': e.get('title', ''),
                        'order': int(e.get('order', 0))})
        pages = int(eps_data.get('eps', {}).get('pages', 1))
        if page >= pages or not eps_list:
            break
        page += 1
    eps.sort(key=lambda e: e['order'])
    return {
        'id': str(comic.get('_id', book_id)),
        'title': comic.get('title', ''),
        'author': comic.get('author', ''),
        'thumb': comic.get('thumb', {}),
        'eps': eps,
    }


def _eps_pages(book_id, eps_order):
    """章节全部图片信息: [{fileServer, path}]（正序）。eps_order 为章节序号(1 基, 非 eps UUID)。"""
    pages = []
    page = 1
    while True:
        data = _api('GET', f'/comics/{book_id}/order/{eps_order}/pages', params={'page': page})
        docs = data.get('pages', {}).get('docs', [])
        for d in docs:
            media = d.get('media', {})
            pages.append({'fileServer': media.get('fileServer', ''),
                          'path': media.get('path', '')})
        total = int(data.get('pages', {}).get('pages', 1))
        if page >= total or not docs:
            break
        page += 1
    return pages


def chapter_pages(book_id, eps_order):
    """章节页数。eps_order 为章节序号(1 基)。"""
    return len(_eps_pages(book_id, eps_order))


def _page_url(page):
    fs = page.get('fileServer', '')
    if fs.endswith('/static/'):
        fs = fs[:-len('/static/')]
    url = fs + '/static/' + page.get('path', '')
    # tobeimg 封面特殊路径: 替换 host + 去 /static/tobeimg 前缀（picacg-qt req.py jumpDomain）
    host = fs.replace('https://', '').replace('http://', '').rstrip('/')
    if '/static/tobeimg' in url and host in IMG_JUMP_DOMAINS:
        url = url.replace(host, IMG_JUMP_DOMAINS[host])
        url = url.replace('/static/tobeimg', '')
        fs = 'https://' + IMG_JUMP_DOMAINS[host]
    return url, fs


def cover(book_id):
    """封面缓存（pika_cover_cache/），不存在则下载。失败返回 None。"""
    os.makedirs(COVER_CACHE_DIR, exist_ok=True)
    path = os.path.join(COVER_CACHE_DIR, f'{book_id}.jpg')
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    try:
        album = album_detail(book_id)
        thumb = album.get('thumb', {})
        url, fs = _page_url(thumb)
        _fetch_image(url, fs, path)
        return path
    except Exception:
        return None


# ===== 搜索 =====

def search(query, page, mode='site', order_by='mr', search_type='keyword', page_size=25):
    """
    站内搜索, 返回 {total, page, items:[{id,title,author,tags,source:pika}]}。
    mode: site=关键词 / id=按 book id 直查
    order_by: mr→da(日期) / mv→vd(浏览) / mp→dd(默认) / tf→ld(点赞)
    search_type: keyword直传 / fuzzy去空白特殊字符 / exact标题完全相等后过滤
    """
    page = max(1, int(page))
    if order_by not in ('mr', 'mv', 'mp', 'tf'):
        order_by = 'mr'
    if search_type not in ('keyword', 'fuzzy', 'exact'):
        search_type = 'keyword'
    if page_size not in (10, 25, 50):
        page_size = 25

    if mode == 'id':
        album = album_detail(query.strip())
        return {
            'total': 1, 'page': 1,
            'items': [{'id': album['id'], 'title': album['title'],
                       'author': album['author'], 'tags': [], 'source': 'pika'}],
        }

    if search_type == 'fuzzy':
        query = re.sub(r'[\s\W_]+', '', query)

    sort_map = {'mr': 'da', 'mv': 'vd', 'mp': 'dd', 'tf': 'ld'}
    sort = sort_map.get(order_by, 'da')

    # 分页: API 单页 20 条, 跨页取足 page_size
    start = (page - 1) * page_size
    end = start + page_size
    api_start = start // API_PAGE_SIZE + 1
    api_end = (end - 1) // API_PAGE_SIZE + 1
    all_docs = []
    for p in range(api_start, api_end + 1):
        data = _api('POST', '/comics/advanced-search', params={'page': p},
                    body={'categories': [], 'keyword': query, 'sort': sort})
        all_docs.extend(data.get('comics', {}).get('docs', []))
        if p == api_start:
            total = int(data.get('comics', {}).get('total', 0))

    items = []
    for c in all_docs[start % API_PAGE_SIZE: start % API_PAGE_SIZE + page_size]:
        items.append({
            'id': str(c.get('_id', '')),
            'title': c.get('title', ''),
            'author': c.get('author', ''),
            'tags': c.get('tags', []),
            'source': 'pika',
        })

    if search_type == 'exact':
        q = query.strip().lower()
        items = [it for it in items if it['title'].strip().lower() == q]

    return {'total': total, 'page': page, 'items': items}


# ===== 下载任务管理 =====

_tasks = {}
_task_lock = threading.Lock()
_queue = []
_worker_started = False


def start_download(book_id, title, author, mode):
    """创建下载任务。mode: temp=阅读(share/temp) / persist=持久化(share 根)。返回 tid。"""
    global _worker_started
    tid = uuid.uuid4().hex[:12]
    with _task_lock:
        for old_tid, t in _tasks.items():
            if (t['aid'] == book_id and t['mode'] == mode
                    and t['status'] in ('queued', 'running')):
                return old_tid
        _tasks[tid] = {
            'tid': tid, 'aid': book_id, 'title': title, 'author': author,
            'mode': mode, 'status': 'queued', 'error': None,
            'target': None, 'count': 0, 'total': 0,
        }
        _queue.append(tid)
        if not _worker_started:
            threading.Thread(target=_download_worker, daemon=True).start()
            _worker_started = True
    return tid


def task_status(tid):
    with _task_lock:
        task = _tasks.get(tid)
        if task is None:
            return None
        if task['status'] == 'running' and task.get('target'):
            t = dict(task)
            base = os.path.join(SHARE_DIR, 'temp') if task['mode'] == 'temp' else SHARE_DIR
            t['count'] = _count_images(os.path.join(base, task['target']))
            return t
        return dict(task)


def _download_worker():
    while True:
        tid = None
        with _task_lock:
            if _queue:
                tid = _queue.pop(0)
        if tid is None:
            time.sleep(1)
            continue
        with _task_lock:
            task = _tasks.get(tid)
            if task is not None:
                task['status'] = 'running'
        if task is None:
            continue
        try:
            album = album_detail(task['aid'])
            eps_list = album['eps']
            if not eps_list:
                raise RuntimeError('该漫画无章节')
            multi = len(eps_list) > 1
            base_dir = os.path.join(SHARE_DIR, 'temp') if task['mode'] == 'temp' else SHARE_DIR
            target = f"{_sanitize(album['author'])}/{_sanitize(album['title'])}"
            with _task_lock:
                task['target'] = target
                task['total'] = sum(len(_eps_pages(task['aid'], e['order'])) for e in eps_list)

            # persist 增量: temp 真实文件合并到根目录
            if task['mode'] == 'persist':
                temp_dir = os.path.join(SHARE_DIR, 'temp', target)
                if os.path.isdir(temp_dir):
                    _merge_move(temp_dir, os.path.join(SHARE_DIR, target),
                                include_placeholders=False)

            count = 0
            for eps in eps_list:
                eps_dir = os.path.join(base_dir, target)
                if multi:
                    eps_dir = os.path.join(eps_dir, _sanitize(eps['title']))
                pages = _eps_pages(task['aid'], eps['order'])
                for i, page in enumerate(pages, 1):
                    dest = os.path.join(eps_dir, f'{i:05d}.jpg')
                    if os.path.exists(dest) and os.path.getsize(dest) > 0:
                        count += 1
                        continue
                    url, fs = _page_url(page)
                    _fetch_image(url, fs, dest)
                    count += 1
                    with _task_lock:
                        task['count'] = count

            _write_aid(os.path.join(base_dir, target), task['aid'])
            with _task_lock:
                task['status'] = 'done'
                task['count'] = count
                if multi:
                    subdirs = sorted(d for d in os.listdir(os.path.join(base_dir, target))
                                     if os.path.isdir(os.path.join(base_dir, target, d)))
                    if subdirs:
                        task['target'] = target + '/' + subdirs[0]
        except Exception as e:
            with _task_lock:
                task['status'] = 'error'
                task['error'] = str(e)


# ===== 在线懒加载阅读 =====

_album_cache = {}
_album_lock = threading.Lock()


def _cached_album(book_id):
    with _album_lock:
        album = _album_cache.get(book_id)
    if album is None:
        album = album_detail(book_id)
        with _album_lock:
            _album_cache[book_id] = album
    return album


def _load_meta(album_dir):
    try:
        with open(os.path.join(album_dir, ONLINE_META_FILE), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _save_meta(album_dir, meta):
    with open(os.path.join(album_dir, ONLINE_META_FILE), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)


def _prep_eps(book_id, eps, album_dir, meta, single):
    """为一个章节 touch 空占位文件并登记 chapters[dir]→eps_order。"""
    pages = _eps_pages(book_id, eps['order'])
    ch_dir = album_dir if single else os.path.join(album_dir, _sanitize(eps['title']))
    os.makedirs(ch_dir, exist_ok=True)
    for i in range(1, len(pages) + 1):
        p = os.path.join(ch_dir, f'{i:05d}.jpg')
        if not os.path.exists(p):
            with open(p, 'a'):
                pass
    meta['chapters']['.' if single else _sanitize(eps['title'])] = eps['order']
    _save_meta(album_dir, meta)
    return ch_dir


def prepare_online(book_id):
    """
    在线阅读入口: 根目录已下载直接返回根路径; 否则 temp 下 touch 空占位 + meta,
    返回 /gallery 相对路径。首章节同步, 其余后台补齐。
    """
    album = _cached_album(book_id)
    author = _sanitize(album['author'])
    name = _sanitize(album['title'])

    persist_dir = os.path.join(SHARE_DIR, author, name)
    if _has_real_images(persist_dir):
        return {'path': f'{author}/{name}'.replace('\\', '/')}
    found = _find_album_dir_by_aid(book_id, SHARE_DIR, skip_dirs=('temp',))
    if found and _has_real_images(found):
        return {'path': os.path.relpath(found, SHARE_DIR).replace('\\', '/')}

    album_dir = os.path.join(SHARE_DIR, 'temp', author, name)
    if not os.path.isdir(album_dir):
        found_temp = _find_album_dir_by_aid(book_id, os.path.join(SHARE_DIR, 'temp'))
        if found_temp:
            album_dir = found_temp
    os.makedirs(album_dir, exist_ok=True)
    _touch_last_read(album_dir)

    eps_list = album['eps']
    single = len(eps_list) == 1
    meta = _load_meta(album_dir)
    if meta is None or meta.get('aid') != book_id or meta.get('source') != 'pika':
        meta = {'source': 'pika', 'aid': book_id, 'chapters': {}, 'single': single}
    first = eps_list[0]
    ch_dir = _prep_eps(book_id, first, album_dir, meta, single)

    remaining = eps_list[1:]
    if remaining:
        def prep_rest():
            for eps in list(remaining):
                try:
                    m = _load_meta(album_dir)
                    if m is None:
                        return
                    _prep_eps(book_id, eps, album_dir, m, single)
                except Exception:
                    pass
        threading.Thread(target=prep_rest, daemon=True).start()

    rel = os.path.relpath(ch_dir, SHARE_DIR).replace('\\', '/')
    return {'path': rel}


def _download_image_to(book_id, eps_order, index, dest_path):
    """把单张图下载到指定绝对路径。eps_order 为章节序号(1 基), index 从 1 起。"""
    pages = _eps_pages(book_id, eps_order)
    if index < 1 or index > len(pages):
        raise IndexError(f'页码越界: {index}/{len(pages)}')
    url, fs = _page_url(pages[index - 1])
    return _fetch_image(url, fs, dest_path)


def materialize_file(rel_path):
    """
    /file 路由按需物化: 命中 pika 空占位时拉真实图。非 pika 结构返回 None。
    """
    full = os.path.join(SHARE_DIR, rel_path)
    if os.path.exists(full) and os.path.getsize(full) > 0:
        return None

    file_dir = os.path.dirname(full)
    meta = _load_meta(file_dir)
    if meta is not None and meta.get('source') == 'pika' and meta.get('single'):
        eps_order = meta['chapters'].get('.')
    else:
        meta = _load_meta(os.path.dirname(file_dir))
        if meta is None or meta.get('source') != 'pika':
            return None
        eps_order = meta['chapters'].get(os.path.basename(file_dir)) if meta else None
    if eps_order is None:
        return None

    m = re.match(r'^(\d+)', os.path.basename(rel_path))
    if not m:
        return None
    index = int(m.group(1))
    try:
        return _download_image_to(meta['aid'], eps_order, index, full)
    except Exception:
        return None


# ===== 检查与持久化 =====

def check_album(book_id):
    """检查下载状态: {downloaded, path, in_temp, temp_path}。"""
    album = _cached_album(book_id)
    author = _sanitize(album['author'])
    name = _sanitize(album['title'])
    persist_dir = os.path.join(SHARE_DIR, author, name)
    temp_dir = os.path.join(SHARE_DIR, 'temp', author, name)
    downloaded = _has_real_images(persist_dir)
    in_temp = _has_real_images(temp_dir)
    if not downloaded:
        found = _find_album_dir_by_aid(book_id, SHARE_DIR, skip_dirs=('temp',))
        if found and _has_real_images(found):
            downloaded = True
            persist_dir = found
    if not in_temp:
        found = _find_album_dir_by_aid(book_id, os.path.join(SHARE_DIR, 'temp'))
        if found and _has_real_images(found):
            in_temp = True
            temp_dir = found
    return {
        'downloaded': downloaded,
        'path': os.path.relpath(persist_dir, SHARE_DIR).replace('\\', '/') if downloaded else None,
        'in_temp': in_temp,
        'temp_path': os.path.relpath(temp_dir, SHARE_DIR).replace('\\', '/') if in_temp else None,
    }


def persist_temp(path):
    """把 temp 下 pika 阅读缓存持久化到根目录（移动语义, 复用 _merge_move）。"""
    share_abs = os.path.abspath(SHARE_DIR)
    src_abs = os.path.abspath(os.path.join(SHARE_DIR, path))
    if not (src_abs == share_abs or src_abs.startswith(share_abs + os.sep)):
        raise ValueError('非法路径: 超出 share 目录')
    rel = os.path.relpath(src_abs, share_abs).replace('\\', '/')
    parts = rel.split('/')
    if not parts or parts[0] != 'temp':
        raise ValueError('非法路径: 必须以 temp/ 开头')
    if len(parts) < 2:
        raise ValueError('非法路径: 缺少作者目录')
    if not os.path.isdir(src_abs):
        raise ValueError('目录不存在: ' + path)

    moved = 0
    skipped = 0
    if len(parts) == 2:
        author = parts[1]
        for name in sorted(os.listdir(src_abs)):
            sub = os.path.join(src_abs, name)
            if not os.path.isdir(sub):
                continue
            dst = os.path.join(share_abs, author, name)
            aid = _read_aid(sub)
            r = _merge_move(sub, dst, include_placeholders=True)
            moved += r['moved']
            skipped += r['skipped']
            _write_aid(dst, aid)
        try:
            os.rmdir(src_abs)
        except OSError:
            pass
    else:
        dst = os.path.join(share_abs, parts[1], parts[2])
        aid = _read_aid(src_abs)
        r = _merge_move(src_abs, dst, include_placeholders=True)
        moved += r['moved']
        skipped += r['skipped']
        _write_aid(dst, aid)
    return {'moved': moved, 'skipped': skipped}


def _read_aid(d):
    """从目录元数据(.jm_online 或 .jm_aid)读取 aid。"""
    try:
        meta = _load_meta(d)
        aid = meta.get('aid') if meta else None
        if not aid:
            aid_file = os.path.join(d, AID_FILE)
            if os.path.isfile(aid_file):
                with open(aid_file, 'r', encoding='utf-8') as f:
                    aid = f.read().strip()
        return aid
    except Exception:
        return None