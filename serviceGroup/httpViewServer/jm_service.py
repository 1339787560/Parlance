# -*- coding: utf-8 -*-
"""
JM 漫画搜索与下载服务（依托 jmcomic 库）。

职责:
- 站内搜索（按关键词/作者/作品），每分页 25 条
- 封面图代理（缓存于服务 cwd 下 jm_cover_cache/，不入 share 库）
- 下载任务管理: 阅读模式（临时, 下载到 share/temp/<作者>/<标题>）
               持久模式（下载到 share/<作者>/<标题>）

下载为后台线程串行执行，前端通过 /jm/status 轮询进度。
"""
import os
import hashlib
import json
import re
import shutil
import threading
import time
import uuid

from const import SHARE_DIR

try:
    from jmcomic import JmModuleConfig
    HAS_JMCOMIC = True
except ImportError:
    HAS_JMCOMIC = False

# 每分页展示条数（jmcomic API 单页返回 80 条，这里切片成 25/页）
PAGE_SIZE = 25
API_PAGE_SIZE = 80

# 封面缓存目录（服务 cwd 下, 不在 share 内避免污染库导航）
COVER_CACHE_DIR = os.path.join(os.path.abspath('.'), 'jm_cover_cache')

# 搜索结果磁盘缓存目录, key=md5(mode|query|page), 6 小时有效
SEARCH_CACHE_DIR = os.path.join(os.path.abspath('.'), 'jm_search_cache')
SEARCH_CACHE_TTL = 6 * 3600

# ===== 服务配置 (jm_config.json, 服务 cwd 下) =====

CONFIG_FILE = os.path.join(os.path.abspath('.'), 'jm_config.json')
DEFAULT_TEMP_RETENTION_DAYS = 7  # temp 阅读缓存保留天数(默认)


def _config_get(key, default=None):
    """读取服务配置项, 文件缺失/损坏返回 default。"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        return cfg.get(key, default)
    except Exception:
        return default


def _config_set(key, value):
    """写入服务配置项(原子替换), 返回写入值。"""
    cfg = {}
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    cfg[key] = value
    tmp = CONFIG_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)
    return value

_client = None
_client_lock = threading.Lock()


def get_client():
    """惰性创建并复用 jmcomic 客户端（默认 api 实现, 搜索结果带 author 字段）。"""
    global _client
    with _client_lock:
        if _client is None:
            opt = JmModuleConfig.option_class().default()
            _client = opt.new_jm_client()
        return _client


def _search_cache_key(mode, query, page, order_by='mr', search_type='keyword', page_size=25, source='jm'):
    raw = f'{mode}|{query}|{page}|{order_by}|{search_type}|{page_size}|{source}'.encode('utf-8')
    return hashlib.md5(raw).hexdigest()


def _search_cache_get(mode, query, page, order_by='mr', search_type='keyword', page_size=25, source='jm'):
    path = os.path.join(SEARCH_CACHE_DIR, _search_cache_key(mode, query, page, order_by, search_type, page_size, source) + '.json')
    if not os.path.isfile(path):
        return None
    try:
        if time.time() - os.path.getmtime(path) > SEARCH_CACHE_TTL:
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _search_cache_put(mode, query, page, result, order_by='mr', search_type='keyword', page_size=25, source='jm'):
    try:
        os.makedirs(SEARCH_CACHE_DIR, exist_ok=True)
        path = os.path.join(SEARCH_CACHE_DIR, _search_cache_key(mode, query, page, order_by, search_type, page_size, source) + '.json')
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def search(query, page, mode='site', order_by='mr', search_type='keyword', page_size=25, source='jm'):
    """
    站内搜索, 返回 {total, page, items:[{id,title,author,tags}]}。
    mode: site=全站 / author=按作者 / work=按作品 / id=按 album id 直查
    order_by: mr=最新 / mv=最多点击 / mp=最多图片 / tf=最多爱心
    search_type: keyword=原样直传 / fuzzy=去空白特殊字符+强制全站 / exact=标题完全相等(大小写不敏感)后过滤
    page_size: 每页条数 (10/25/50, 默认 25)
    source: 数据源 (仅 jm 实现, pic 留白)
    结果按 (mode, query, page, order_by, search_type, page_size, source) 磁盘缓存 6 小时。
    """
    page = max(1, int(page))
    if order_by not in ('mr', 'mv', 'mp', 'tf'):
        order_by = 'mr'
    if search_type not in ('keyword', 'fuzzy', 'exact'):
        search_type = 'keyword'
    if page_size not in (10, 25, 50):
        page_size = 25

    # 按 album id 直查（不走磁盘缓存, 不受 search_type 语义影响）
    if mode == 'id':
        album = get_client().get_album_detail(query.strip())
        return {
            'total': 1,
            'page': 1,
            'items': [{
                'id': album.album_id,
                'title': album.name,
                'author': album.author,
                'tags': album.tags,
            }],
        }

    # fuzzy: 放宽匹配 — 去掉空白/特殊字符, 强制全站范围
    if search_type == 'fuzzy':
        query = re.sub(r'[\s\W_]+', '', query)
        mode = 'site'

    cached = _search_cache_get(mode, query, page, order_by, search_type, page_size, source)
    if cached is not None:
        return cached

    # 把 page_size/页 的展示分页映射到 API 的 80/页
    offset = (page - 1) * page_size
    api_page = offset // API_PAGE_SIZE + 1
    api_offset = offset % API_PAGE_SIZE

    client = get_client()
    if mode == 'author':
        result = client.search_author(query, page=api_page, order_by=order_by)
    elif mode == 'work':
        result = client.search_work(query, page=api_page, order_by=order_by)
    else:
        result = client.search_site(query, page=api_page, order_by=order_by)

    items = []
    for aid, ainfo in result.content[api_offset:api_offset + page_size]:
        items.append({
            'id': aid,
            'title': ainfo.get('name', ''),
            'author': ainfo.get('author', ''),
            'tags': ainfo.get('tags', []),
        })

    # exact: 结果后过滤 title 与 query 完全相等(大小写不敏感)的条目
    if search_type == 'exact':
        q = query.strip().lower()
        items = [it for it in items if it['title'].strip().lower() == q]

    ret = {
        'total': int(result.total or 0),
        'page': page,
        'items': items,
    }
    _search_cache_put(mode, query, page, ret, order_by, search_type, page_size, source)
    return ret


def cover_path(album_id):
    """获取封面缓存路径, 不存在则下载。失败返回 None。"""
    os.makedirs(COVER_CACHE_DIR, exist_ok=True)
    path = os.path.join(COVER_CACHE_DIR, f'{album_id}.jpg')
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    try:
        get_client().download_album_cover(album_id, path)
        return path
    except Exception:
        return None


# ===== 下载任务管理 =====

_tasks = {}           # tid -> task dict
_task_lock = threading.Lock()
_queue = []           # 待执行 tid 队列（串行）
_worker_started = False


def _sanitize(name):
    return re.sub(r'[\\/:*?"<>|]+', '_', (name or '').strip()) or 'unknown'


def _count_images(target_dir):
    if not target_dir or not os.path.isdir(target_dir):
        return 0
    n = 0
    for _, _, files in os.walk(target_dir):
        n += sum(1 for f in files if os.path.splitext(f)[1].lower()
                 in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'))
    return n


def _resolve_target(album):
    """依据 album 实体计算相对 share 的目标目录（作者/标题）。"""
    author = _sanitize(album.author)
    name = _sanitize(album.name)
    return f'{author}/{name}'


# ===== 持久化 (temp → share 根, 移动语义) =====

LAST_READ_FILE = '.jm_last_read'  # 记录最近阅读时间, 供 temp 回收判断
AID_FILE = '.jm_aid'  # 根目录专辑 aid 标记(供 aid 反查, 应对名称变体不一致如简繁)


def _merge_move(src, dst, include_placeholders=False):
    """
    把 src 树中的真实文件(>0字节)合并移动到 dst 树。
    - 跳过 .jm_last_read 元数据文件
    - include_placeholders=True(持久化): 空占位与 .jm_online 元数据一并迁移,
      使目标目录完整且 /file 可按需物化; False(增量下载): 跳过, 避免 jmcomic 跳过空文件
    - 目标已存在跳过; dst 目录自动创建(含作者文件夹)
    - 移动后清理 src 空目录
    返回 {moved, skipped}。
    """
    moved = 0
    skipped = 0
    if not os.path.isdir(src):
        return {'moved': 0, 'skipped': 0}
    os.makedirs(dst, exist_ok=True)
    for root, _, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst if rel == '.' else os.path.join(dst, rel)
        os.makedirs(target_root, exist_ok=True)
        for f in files:
            if f == LAST_READ_FILE:
                continue
            if f == ONLINE_META_FILE and not include_placeholders:
                continue
            sp = os.path.join(root, f)
            dp = os.path.join(target_root, f)
            if os.path.getsize(sp) == 0 and not include_placeholders:
                skipped += 1
                continue
            if os.path.exists(dp):
                skipped += 1
                continue
            os.replace(sp, dp)
            moved += 1
    # 清理源残留: 删除元数据与空占位(0字节)文件, 使源目录可被清空;
    # 真实文件(含"目标已存在"跳过的)保留, 避免数据丢失
    for root, _, files in os.walk(src, topdown=False):
        for f in files:
            p = os.path.join(root, f)
            try:
                if f == LAST_READ_FILE or (os.path.getsize(p) == 0 and not include_placeholders):
                    os.remove(p)
            except OSError:
                pass
        # 清理源空目录(自底向上, 非空目录 rmdir 失败自动忽略)
        try:
            os.rmdir(root)
        except OSError:
            pass
    return {'moved': moved, 'skipped': skipped}


def persist_temp(path):
    """
    把 temp 下的阅读缓存持久化到 share 根目录(移动语义)。
    path 相对 share: temp/<作者> 或 temp/<作者>/<标题>。
    - 校验: 以 temp/ 开头且解析后仍在 SHARE_DIR 内(防目录穿越)
    - 段数==2(temp/<作者>) → 作者级: 遍历其下每个子目录(漫画)逐个移动
    - 段数>=3 → 漫画级: 整树移动
    返回 {moved, skipped}。
    """
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
        # 作者级: 每个子目录(漫画)移动到 share/<作者>/<标题>
        author = parts[1]
        for name in sorted(os.listdir(src_abs)):
            sub = os.path.join(src_abs, name)
            if not os.path.isdir(sub):
                continue
            dst = os.path.join(share_abs, author, name)
            aid = _read_aid_from_dir(sub)  # 移动前读 aid(meta 会随迁移)
            r = _merge_move(sub, dst, include_placeholders=True)
            moved += r['moved']
            skipped += r['skipped']
            _write_aid(dst, aid)
        # 清理空作者目录
        try:
            os.rmdir(src_abs)
        except OSError:
            pass
    else:
        # 漫画级: 整树移动到 share/<作者>/<标题>
        dst = os.path.join(share_abs, parts[1], parts[2])
        aid = _read_aid_from_dir(src_abs)
        r = _merge_move(src_abs, dst, include_placeholders=True)
        moved += r['moved']
        skipped += r['skipped']
        _write_aid(dst, aid)
    return {'moved': moved, 'skipped': skipped}


def _has_real_images(d):
    """目录树内是否存在真实图片(>0字节, 跳过点开头元数据)。"""
    if not os.path.isdir(d):
        return False
    for root, _, files in os.walk(d):
        for f in files:
            if f.startswith('.'):
                continue
            if os.path.getsize(os.path.join(root, f)) > 0:
                return True
    return False


def _find_album_dir_by_aid(aid, base_dir, skip_dirs=()):
    """
    在 base_dir 下扫描 <作者>/<标题> 目录, 通过元数据(.jm_online/.jm_aid)反查 aid 匹配的专辑目录。
    用于名称变体不一致(如 jmcomic API 简繁切换)时兜底定位。
    返回专辑目录绝对路径或 None。
    """
    aid = str(aid)
    if not os.path.isdir(base_dir):
        return None
    for author in os.listdir(base_dir):
        if author in skip_dirs:
            continue
        author_dir = os.path.join(base_dir, author)
        if not os.path.isdir(author_dir):
            continue
        for name in os.listdir(author_dir):
            album_dir = os.path.join(author_dir, name)
            if not os.path.isdir(album_dir):
                continue
            meta = _online_load_meta(album_dir)  # .jm_online (temp 阅读元数据)
            if meta and str(meta.get('aid', '')) == aid:
                return album_dir
            aid_file = os.path.join(album_dir, AID_FILE)
            if os.path.isfile(aid_file):
                try:
                    with open(aid_file, 'r', encoding='utf-8') as f:
                        if str(f.read().strip()) == aid:
                            return album_dir
                except Exception:
                    pass
    return None


def _read_aid_from_dir(d):
    """从目录元数据(.jm_online 或 .jm_aid)读取 aid, 无则 None。"""
    try:
        meta = _online_load_meta(d)
        aid = meta.get('aid') if meta else None
        if not aid:
            aid_file = os.path.join(d, AID_FILE)
            if os.path.isfile(aid_file):
                with open(aid_file, 'r', encoding='utf-8') as f:
                    aid = f.read().strip()
        return aid
    except Exception:
        return None


def _write_aid(dst_dir, aid):
    """在专辑目录写入 .jm_aid 标记(供后续 aid 反查)。"""
    try:
        if not aid:
            return
        os.makedirs(dst_dir, exist_ok=True)
        with open(os.path.join(dst_dir, AID_FILE), 'w', encoding='utf-8') as f:
            f.write(str(aid))
    except Exception:
        pass


def check_album(aid):
    """
    检查专辑下载状态。
    返回 {downloaded, path, in_temp, temp_path}:
    - downloaded: share/<作者>/<标题> 是否有真实图片
    - path: 持久化相对路径(作者/标题)或 None
    - in_temp: share/temp/<作者>/<标题> 是否有真实图片
    - temp_path: temp 相对路径或 None
    """
    album = _cached_album(aid)
    author = _sanitize(album.author)
    name = _sanitize(album.name)
    persist_dir = os.path.join(SHARE_DIR, author, name)
    temp_dir = os.path.join(SHARE_DIR, 'temp', author, name)
    downloaded = _has_real_images(persist_dir)
    in_temp = _has_real_images(temp_dir)
    # aid 反查兜底: 名称变体不一致(如简繁)时按 .jm_online/.jm_aid 元数据定位
    if not downloaded:
        found = _find_album_dir_by_aid(aid, SHARE_DIR, skip_dirs=('temp',))
        if found and _has_real_images(found):
            downloaded = True
            persist_dir = found
    if not in_temp:
        found = _find_album_dir_by_aid(aid, os.path.join(SHARE_DIR, 'temp'))
        if found and _has_real_images(found):
            in_temp = True
            temp_dir = found
    return {
        'downloaded': downloaded,
        'path': os.path.relpath(persist_dir, SHARE_DIR).replace('\\', '/') if downloaded else None,
        'in_temp': in_temp,
        'temp_path': os.path.relpath(temp_dir, SHARE_DIR).replace('\\', '/') if in_temp else None,
    }


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
            base_dir = os.path.join(SHARE_DIR, 'temp') if task['mode'] == 'temp' else SHARE_DIR

            # 预取详情: 提前确定目标目录与总页数, 使进度条可用;
            # 分集漫画(多章节)在专辑目录下按章节名建子目录, 避免同名图片互相覆盖
            rule = 'Bd/{Aauthor}/{Aname}'
            multi_chapter = False
            try:
                album = get_client().get_album_detail(task['aid'])
                total = album.page_count
                if not total:
                    # API 对单章节 album 常返回 page_count=0, 逐章节取图数兜底
                    client = get_client()
                    total = sum(
                        len(client.get_photo_detail(pid).page_arr or [])
                        for pid, _, _ in album.episode_list
                    )
                multi_chapter = len(album.episode_list) > 1
                if multi_chapter:
                    rule = 'Bd/{Aauthor}/{Aname}/{Pname}'
                with _task_lock:
                    task['target'] = _resolve_target(album)
                    task['total'] = total
            except Exception:
                pass

            # 增量下载(persist 模式): 先把 temp 下已物化的真实文件合并到根目录,
            # jmcomic 下载器原生跳过已存在文件, 只补缺失
            if task['mode'] == 'persist' and task.get('target'):
                temp_dir = os.path.join(SHARE_DIR, 'temp', task['target'])
                if os.path.isdir(temp_dir):
                    _merge_move(temp_dir, os.path.join(SHARE_DIR, task['target']))

            opt = JmModuleConfig.option_class().construct({
                'dir_rule': {'rule': rule, 'base_dir': base_dir},
            })

            from jmcomic import download_album
            download_album(task['aid'], option=opt)

            # 下载完成后写 .jm_aid 标记(供 aid 反查, 应对名称变体不一致)
            if task.get('target'):
                _write_aid(os.path.join(base_dir, task['target']), task['aid'])

            with _task_lock:
                task['status'] = 'done'
                if task.get('target'):
                    target_abs = os.path.join(base_dir, task['target'])
                    # 分集漫画: 阅读入口指向第一个章节子目录
                    if multi_chapter:
                        subdirs = sorted(d for d in os.listdir(target_abs)
                                         if os.path.isdir(os.path.join(target_abs, d)))
                        if subdirs:
                            task['target'] = task['target'] + '/' + subdirs[0]
                    task['count'] = _count_images(target_abs)
                else:
                    task['count'] = 0
        except Exception as e:
            with _task_lock:
                task['status'] = 'error'
                task['error'] = str(e)


def start_download(aid, title, author, mode):
    """
    创建下载任务。
    mode: 'temp'=阅读（share/temp 下）/ 'persist'=持久化（share 根下）
    返回 tid。
    """
    global _worker_started
    if not HAS_JMCOMIC:
        raise RuntimeError('jmcomic 未安装')

    tid = uuid.uuid4().hex[:12]
    with _task_lock:
        # 同一 album + mode 的运行中任务直接复用
        for old_tid, t in _tasks.items():
            if (t['aid'] == aid and t['mode'] == mode
                    and t['status'] in ('queued', 'running')):
                return old_tid
        _tasks[tid] = {
            'tid': tid, 'aid': aid, 'title': title, 'author': author,
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
        # 运行中实时统计已落盘图片数
        if task['status'] == 'running' and task.get('target'):
            t = dict(task)
            t['count'] = _count_images(
                os.path.join(
                    os.path.join(SHARE_DIR, 'temp') if task['mode'] == 'temp' else SHARE_DIR,
                    task['target']))
            return t
        return dict(task)


# ===== 在线懒加载阅读 =====

_album_cache = {}     # aid -> JmAlbumDetail
_photo_cache = {}     # (aid, pid) -> JmPhotoDetail
_lazy_lock = threading.Lock()


def album_chapters(aid):
    """返回专辑元信息与章节列表: {id,title,author,chapters:[{pid,title}]}。"""
    album = _cached_album(aid)
    chapters = [{'pid': pid, 'title': pname} for pid, _, pname in album.episode_list]
    return {
        'id': album.album_id,
        'title': album.name,
        'author': album.author,
        'chapters': chapters,
    }


def _cached_album(aid):
    with _lazy_lock:
        album = _album_cache.get(aid)
    if album is None:
        album = get_client().get_album_detail(aid)
        with _lazy_lock:
            _album_cache[aid] = album
    return album


def _cached_photo(aid, pid):
    key = (aid, pid)
    with _lazy_lock:
        photo = _photo_cache.get(key)
    if photo is None:
        photo = get_client().get_photo_detail(pid)
        with _lazy_lock:
            _photo_cache[key] = photo
    return photo


def chapter_pages(aid, pid):
    """返回章节页数: {pid, title, count}。"""
    photo = _cached_photo(aid, pid)
    return {'pid': pid, 'title': photo.name, 'count': len(photo.page_arr or [])}


def _download_image_to(aid, pid, index, dest_path):
    """把单张图下载(含解密)到指定绝对路径。"""
    photo = _cached_photo(aid, pid)
    page_arr = photo.page_arr or []
    if index < 1 or index > len(page_arr):
        raise IndexError(f'页码越界: {index}/{len(page_arr)}')
    image = photo.create_image_detail(index - 1)  # create_image_detail 为 0 基
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    # 临时文件需保留图片后缀, 否则 PIL 按扩展名推断格式会失败
    tmp = dest_path + '.tmp' + image.img_file_suffix
    get_client().download_by_image_detail(image, tmp)
    os.replace(tmp, dest_path)
    return dest_path


# ===== 在线阅读(复用 viewserver gallery): 空占位文件 + /file 按需物化 =====

ONLINE_META_FILE = '.jm_online'  # 无后缀, 避免被浏览/阅读当成媒体或文本项
_online_prep_lock = threading.Lock()


def _online_meta_path(album_dir):
    return os.path.join(album_dir, ONLINE_META_FILE)


def _online_load_meta(album_dir):
    try:
        with open(_online_meta_path(album_dir), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _online_save_meta(album_dir, meta):
    with open(_online_meta_path(album_dir), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)


def _online_prep_chapter(aid, pid, album_dir, meta):
    """为一个章节 touch 出空占位图片文件(已存在的实文件不动), 并登记 chapter_dir -> pid。"""
    photo = _cached_photo(aid, pid)
    single = meta.get('single', False)
    ch_dir = album_dir if single else os.path.join(album_dir, _sanitize(photo.name))
    os.makedirs(ch_dir, exist_ok=True)
    for i in range(1, len(photo.page_arr or []) + 1):
        image = photo.create_image_detail(i - 1)  # 0 基
        p = os.path.join(ch_dir, image.img_file_name + image.img_file_suffix)
        if not os.path.exists(p):
            with open(p, 'a'):
                pass
    if not single:
        meta['chapters'][_sanitize(photo.name)] = pid
    else:
        meta['chapters']['.'] = pid
    _online_save_meta(album_dir, meta)
    return ch_dir


def prepare_online(aid):
    """
    在线阅读入口: 在 share/temp/<作者>/<标题>/ 下 touch 空占位文件,
    返回可直接交给 /gallery/ 的相对路径。
    首章节同步准备(秒级, 只需 1 次章节详情请求), 其余章节后台补齐,
    gallery 漫画模式滚动到结尾时能自动拼上后续章节。
    若 share/<作者>/<标题> 已有真实图片(已持久化), 直接返回持久化路径, 不建占位。
    """
    album = _cached_album(aid)
    author = _sanitize(album.author)
    name = _sanitize(album.name)

    # 已持久化: 直接指向根目录(名称匹配 + aid 反查兜底), 跳过 temp 物化
    persist_dir = os.path.join(SHARE_DIR, author, name)
    if _has_real_images(persist_dir):
        return {'path': f'{author}/{name}'.replace('\\', '/')}
    found = _find_album_dir_by_aid(aid, SHARE_DIR, skip_dirs=('temp',))
    if found and _has_real_images(found):
        return {'path': os.path.relpath(found, SHARE_DIR).replace('\\', '/')}

    # temp 物化: 名称匹配; 目录不存在时 aid 反查复用旧目录(名称变体不一致场景)
    album_dir = os.path.join(SHARE_DIR, 'temp', author, name)
    if not os.path.isdir(album_dir):
        found_temp = _find_album_dir_by_aid(aid, os.path.join(SHARE_DIR, 'temp'))
        if found_temp:
            album_dir = found_temp
    os.makedirs(album_dir, exist_ok=True)
    _touch_last_read(album_dir)

    with _online_prep_lock:
        meta = _online_load_meta(album_dir)
        if meta is None or meta.get('aid') != aid:
            meta = {'aid': aid, 'chapters': {},
                    'single': len(album.episode_list) == 1}
        first_pid = album.episode_list[0][0]
        ch_dir = _online_prep_chapter(aid, first_pid, album_dir, meta)

    remaining = [pid for pid, _, _ in album.episode_list[1:]]
    if remaining:
        def prep_rest():
            for pid in list(remaining):
                try:
                    with _online_prep_lock:
                        meta = _online_load_meta(album_dir)
                        if meta is None:
                            return
                        _online_prep_chapter(aid, pid, album_dir, meta)
                except Exception:
                    pass
        threading.Thread(target=prep_rest, daemon=True).start()

    rel = os.path.relpath(ch_dir, SHARE_DIR).replace('\\', '/')
    return {'path': rel}


def materialize_file(rel_path):
    """
    /file 路由的按需物化入口: rel_path 命中空占位文件时, 从 JM 拉取真实图片。
    返回物化后的绝对路径; 不属于在线占位结构时返回 None。
    """
    full = os.path.join(SHARE_DIR, rel_path)
    if os.path.exists(full) and os.path.getsize(full) > 0:
        return None  # 已是实文件, 走正常 send_file

    file_dir = os.path.dirname(full)
    # meta 在章节目录(单章节: 文件直接放专辑目录)或其父目录(多章节: 章节/专辑两层)
    meta = _online_load_meta(file_dir)
    album_dir = file_dir
    if meta is not None and meta.get('single'):
        pid = meta['chapters'].get('.')
    else:
        album_dir = os.path.dirname(file_dir)
        meta = _online_load_meta(album_dir)
        pid = meta['chapters'].get(os.path.basename(file_dir)) if meta else None
    if pid is None:
        return None

    m = re.match(r'^(\d+)', os.path.basename(rel_path))
    if not m:
        return None
    index = int(m.group(1))
    result = _download_image_to(meta['aid'], pid, index, full)
    _touch_last_read(album_dir)
    return result


def fetch_page(aid, pid, index):
    """
    按需物化单张图片到 share/temp/<作者>/<标题>/online/<pid>/<文件名>, 返回绝对路径。
    已存在则直接复用。index 从 1 起。
    """
    album = _cached_album(aid)
    photo = _cached_photo(aid, pid)
    page_arr = photo.page_arr or []
    if index < 1 or index > len(page_arr):
        raise IndexError(f'页码越界: {index}/{len(page_arr)}')

    # 与 JmPhotoDetail 对齐的图实体（含 download_url/scramble_id/文件名）
    image = photo.create_image_detail(index - 1)  # create_image_detail 为 0 基
    target_dir = os.path.join(
        SHARE_DIR, 'temp', _sanitize(album.author), _sanitize(album.name), 'online', str(pid))
    path = os.path.join(target_dir, image.img_file_name + image.img_file_suffix)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    return _download_image_to(aid, pid, index, path)


# ===== temp 定期回收 =====

CLEANUP_INTERVAL = 24 * 3600  # 回收扫描周期: 24h


def _touch_last_read(album_dir):
    """touch .jm_last_read 记录最近阅读时间(供回收判断)。"""
    try:
        os.makedirs(album_dir, exist_ok=True)
        p = os.path.join(album_dir, LAST_READ_FILE)
        with open(p, 'a'):
            os.utime(p, None)
    except Exception:
        pass


def _album_last_read(album_dir):
    """专辑最近阅读时间: .jm_last_read mtime, 缺失则用专辑目录 mtime。"""
    lr = os.path.join(album_dir, LAST_READ_FILE)
    if os.path.isfile(lr):
        return os.path.getmtime(lr)
    return os.path.getmtime(album_dir)


def _cleanup_expired_temp():
    """
    扫描 share/temp/<作者>/<专辑>, 删除超过保留期(默认 7 天)的专辑目录,
    并清理空作者目录。保留期从 jm_config.json 的 temp_retention_days 读取。
    """
    days = _config_get('temp_retention_days', DEFAULT_TEMP_RETENTION_DAYS)
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = DEFAULT_TEMP_RETENTION_DAYS
    if days < 1:
        days = DEFAULT_TEMP_RETENTION_DAYS
    cutoff = time.time() - days * 86400

    temp_root = os.path.join(SHARE_DIR, 'temp')
    if not os.path.isdir(temp_root):
        return
    for author in os.listdir(temp_root):
        author_dir = os.path.join(temp_root, author)
        if not os.path.isdir(author_dir):
            continue
        for name in os.listdir(author_dir):
            album_dir = os.path.join(author_dir, name)
            if not os.path.isdir(album_dir):
                continue
            try:
                if _album_last_read(album_dir) < cutoff:
                    shutil.rmtree(album_dir)
            except Exception:
                pass
        # 清理空作者目录
        try:
            os.rmdir(author_dir)
        except OSError:
            pass


def _cleanup_worker():
    """后台回收线程: 每 24h 执行一次 temp 过期清理。"""
    while True:
        try:
            _cleanup_expired_temp()
        except Exception:
            pass
        time.sleep(CLEANUP_INTERVAL)


# 模块加载时启动回收线程(daemon)
threading.Thread(target=_cleanup_worker, daemon=True).start()
