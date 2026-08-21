import os
import re
import sys
import json
from datetime import datetime
from flask import request

from const import *

# 聚合搜索目录前缀。以此前缀开头的目录被视为聚合搜索目录（持久化、存放指向搜索结果的索引）。
AGGSEARCH_PREFIX = '__aggsearch__'

def is_aggsearch_dir(name):
    """判断目录名是否为聚合搜索目录"""
    return name.startswith(AGGSEARCH_PREFIX)

def is_windows_client():
    """通过User-Agent检测是否为Windows客户端"""
    user_agent = request.headers.get('User-Agent', '')
    return re.search(r'Windows', user_agent, re.IGNORECASE)

def get_gallery_folders():
    return [f for f in os.listdir(SHARE_DIR) 
            if os.path.isdir(os.path.join(SHARE_DIR, f))]

# 修复类型判断函数
def is_image_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_IMAGE_EXT  # 改为使用IMAGE_EXT

def is_video_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_VIDEO_EXT

def is_text_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_TEXT_EXT

def get_position(request):
    """统一获取位置参数"""
    pos = request.args.get('pos') or request.args.get('ls_pos') or 1
    return int(pos)

def resource_path(relative_path):
    """获取打包后的资源路径"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def contains_images(path):
    for f in os.listdir(path):
        if os.path.isdir(f):
            if contains_images(os.path.join(path, f)):
                return True
        elif is_image_file(f):
            return True
    return False

def is_image_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXT

def contains_media(path):
    # 同时检查图片和视频文件
    for f in os.listdir(path):
        full_path = os.path.join(path, f)
        if os.path.isdir(full_path):
            if contains_media(full_path):
                return True
        elif is_image_file(f) or is_video_file(f) or is_text_file(f):
            return True
    return False

def is_html_file(filename):
    return os.path.splitext(filename)[1].lower() in ('.html', '.htm')

# def contains_html(path):
#     return any(is_html_file(f) for f in os.listdir(path))

def contains_html(path):
    """判断目录是否为页面库
    页面库定义：至少包含一个html文件，可能包含ServerData文件夹
    """
    if not os.path.isdir(path):
        return False
        
    # 检查是否包含HTML文件
    has_html = any(is_html_file(f) for f in os.listdir(path))
    
    # 如果包含HTML文件，则判断为页面库
    return has_html

def get_first_html_file(path):
    """获取目录中的第一个HTML文件"""
    if not os.path.isdir(path):
        return None
        
    html_files = sorted([f for f in os.listdir(path) if is_html_file(f)])
    return html_files[0] if html_files else None

def build_html_items(folder_path, parent_path=''):
    """构建HTML文件条目列表"""
    items = []
    for filename in sorted(os.listdir(folder_path)):
        file_path = os.path.join(folder_path, filename)
        if os.path.isfile(file_path) and is_html_file(filename):
            # 生成相对路径
            rel_path = os.path.join(parent_path, filename).replace('\\', '/')
            items.append({
                'type': 'html',
                'name': filename,
                'path': rel_path,
                'size': os.path.getsize(file_path)
            })
    return items

# 在browse_directory函数前添加以下代码
def build_directory_items(current_path, subpath):
    """构建目录条目"""
    dir_items = []
    text_items = []
    
    # 获取漫画模式参数
    comic_mode = request.args.get('comic_mode', '').lower() == 'true'
    
    # 分别收集目录项和文本文件项
    for item in os.listdir(current_path):
        item_path = os.path.join(current_path, item)
        if os.path.isdir(item_path):
            if is_aggsearch_dir(item):
                dir_items.append(('aggsearch', item, subpath))
            elif contains_media(item_path):
                dir_items.append(('gallery', item, subpath))
            else:
                dir_items.append(('folder', item, subpath))
        elif is_text_file(item):
            text_items.append(('text', item, subpath))
    
    # 定义提取第一个数字的函数
    def extract_number_prefix(name):
        # 提取名称开头的数字前缀
        match = re.match(r'^(\d+)', name)
        return int(match.group(1)) if match else float('inf')  # 非数字前缀的放到最后
    
    # 定义提取名称中第一个数字的函数（用于漫画模式）
    def extract_first_number(name):
        # 提取名称中第一个出现的数字
        match = re.search(r'(\d+)', name)
        return int(match.group(1)) if match else float('inf')  # 没有数字的放到最后
    
    # 根据漫画模式选择排序方式
    if comic_mode:
        # 漫画模式：按名称中第一个出现的数字排序
        dir_items.sort(key=lambda x: extract_first_number(x[1]))
    else:
        # 普通模式：按名称开头的数字前缀排序
        dir_items.sort(key=lambda x: extract_number_prefix(x[1]))
    
    # 合并目录项和文本文件项
    items = dir_items + text_items
    
    return items

def build_breadcrumbs(subpath):
    """构建面包屑导航"""
    breadcrumbs = []
    parts = subpath.split('/')
    for i in range(len(parts)):
        breadcrumbs.append(('/browse/' + '/'.join(parts[:i+1]), parts[i]))
    return breadcrumbs


# ===== 聚合搜索相关 =====

def _agg_match_term(haystack, term, case_sensitive, whole_word):
    """判断单个关键词是否匹配。haystack 已按大小写设置预处理。"""
    term = term.strip()
    if not term:
        return False
    if not case_sensitive:
        term = term.lower()
    if whole_word:
        # 全字匹配：关键词前后不能紧邻 [A-Za-z0-9_]。
        # 对 CJK 字符而言，非字母数字即视为边界，近似可用。
        pattern = r'(?<![A-Za-z0-9_])' + re.escape(term) + r'(?![A-Za-z0-9_])'
        return re.search(pattern, haystack) is not None
    return term in haystack


def agg_match_query(filename, query, case_sensitive, whole_word):
    """
    判断文件名是否匹配查询表达式。
    查询语法：'|' 表示满足其一（OR），'&' 表示同时满足（AND），& 优先级高于 |。
    例如 '猫|狗' -> 含猫或含狗；'猫&狗' -> 同时含猫和狗；'猫|狗&鱼' -> 含猫，或同时含狗和鱼。
    """
    haystack = filename if case_sensitive else filename.lower()
    for or_group in query.split('|'):
        terms = [t for t in or_group.split('&') if t.strip()]
        if terms and all(_agg_match_term(haystack, t, case_sensitive, whole_word) for t in terms):
            return True
    return False


def find_matching_videos(root_full, query, case_sensitive, whole_word):
    """以 root_full 为根递归搜索匹配的视频文件，返回相对于 SHARE_DIR 的路径列表。"""
    share_abs = os.path.abspath(SHARE_DIR)
    matches = []
    for dirpath, dirnames, filenames in os.walk(root_full):
        # 跳过聚合搜索目录，避免把已建立的索引重复纳入搜索
        dirnames[:] = [d for d in dirnames if not is_aggsearch_dir(d)]
        for f in filenames:
            if is_video_file(f) and agg_match_query(f, query, case_sensitive, whole_word):
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, share_abs).replace('\\', '/')
                matches.append(rel)
    return sorted(matches)


def create_aggsearch_dir(root, query, case_sensitive, whole_word, matches):
    """
    在 root 目录下创建一个持久化的聚合搜索目录，并写入索引文件 index.json。
    返回相对于 SHARE_DIR 的目录路径。
    """
    display = query.strip()[:40] if query.strip() else 'search'
    # 去除文件系统非法字符与空白，生成安全的显示名
    safe = re.sub(r'[\\/:*?"<>|\s]+', '_', display).strip('_') or 'search'
    base_name = AGGSEARCH_PREFIX + safe
    parent_path = os.path.join(SHARE_DIR, root) if root else SHARE_DIR
    target = os.path.join(parent_path, base_name)
    idx = 2
    while os.path.exists(target):
        target = os.path.join(parent_path, f'{base_name}_{idx}')
        idx += 1
    os.makedirs(target)

    meta = {
        'query': query,
        'case_sensitive': case_sensitive,
        'whole_word': whole_word,
        'root': root,
        'created': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'count': len(matches),
        'files': matches,
    }
    with open(os.path.join(target, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return os.path.relpath(os.path.abspath(target), os.path.abspath(SHARE_DIR)).replace('\\', '/')