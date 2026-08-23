from const import *
# from turtle import position
from commonFuncs import *
from flask import Flask, abort, make_response, redirect, render_template, request, send_file, send_from_directory,Response, url_for, jsonify  # 新增导入

import os
import json
import shutil

try:
    from docx import Document
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

app = Flask(__name__)

image_url_mapping = {}
#  route
# 新增图片查看路由
# 在view_photo路由中增加文件类型过滤
# 修改view_photo函数以支持间隔参数
@app.route('/photo/<path:folder>/<int:position>')
def view_photo(folder, position):
    gallery_path = os.path.join(SHARE_DIR, folder)
    # 增加文件类型过滤
    all_images = sorted([f for f in os.listdir(gallery_path)
                    if os.path.splitext(f)[1].lower() in ALLOWED_EXT])
    total_original = len(all_images)  # 保存原始总数量
    
    # 获取间隔参数，默认为0（表示不间隔）
    interval = request.args.get('interval', '0')
    try:
        interval = max(0, int(interval))  # 确保interval是非负整数
    except ValueError:
        interval = 0
    
    # 根据间隔参数过滤图片
    if interval > 0:
        # 按照每n张图片发送一张的规则
        # 这里我们保留位置1, 1+n, 1+2n, ...的图片
        images = [all_images[i] for i in range(len(all_images)) if i % (interval + 1) == 0]
        # 调整position到过滤后的列表中的位置
        # 由于过滤后图片变少，需要重新计算对应的位置
        filtered_position = min(int((position - 1) / (interval + 1)) + 1, len(images)) if images else 1
        current = filtered_position
        total = len(images)
    else:
        # 不间隔，使用原始列表
        images = all_images
        current = position
        total = total_original
        
    # 验证position是否有效
    if current < 1 or current > total:
        return "Invalid position", 404
        
    return render_template('gallery.html',
                         images=images,
                         folder=folder,
                         current=current,
                         total=total,
                         total_original=total_original,  # 传递原始总数量
                         interval=interval)  # 传递当前使用的间隔参数

@app.route('/html/<path:filename>')
def handle_html_file(filename):
    filepath = os.path.join(SHARE_DIR, filename)
    if not os.path.exists(filepath) or not os.path.isfile(filepath):
        abort(404)
    
    # 尝试多种编码读取文件内容
    encodings = ['utf-8', 'utf-16', 'gbk', 'latin-1']
    content = None
    
    for encoding in encodings:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue
    
    if content is None:
        return "无法解码文件内容", 500
    
    # 获取当前HTML文件所在目录的相对路径
    html_dir = os.path.dirname(filename)
    
    # 修改图片链接，添加目录标识，例如 /ServerData/path/to/html/2_1.jpg
    import re
    content = re.sub(r'src="ServerData/([^"]+)"', 
                    lambda m: f'src="/ServerData/{html_dir}/ServerData/{m.group(1)}"', 
                    content)
    
    return content

@app.route('/file/<path:filepath>')
def serve_file(filepath):
    # 在线阅读占位文件: 命中空文件且属于 JM/Pika 在线结构时按需物化
    if HAS_JM:
        try:
            real = jm_service.materialize_file(filepath)
            if real:
                return send_file(real)
        except Exception:
            pass
    if HAS_PIKA:
        try:
            real = pika_service.materialize_file(filepath)
            if real:
                return send_file(real)
        except Exception:
            pass
    return send_from_directory(SHARE_DIR, filepath)

@app.route('/browse/<path:subpath>')
def browse_directory(subpath):
    current_path = os.path.join(SHARE_DIR, subpath)

    # 聚合搜索目录：直接重定向到聚合视图，避免展示内部的 index.json
    if os.path.isdir(current_path) and is_aggsearch_dir(os.path.basename(current_path)):
        return redirect(url_for('aggview', aggdir=subpath))

    # 优先检查是否是媒体文件夹
    if any(os.path.isdir(os.path.join(current_path, f)) for f in os.listdir(current_path)):
        return render_template('index.html', 
                            items=build_directory_items(current_path, subpath),
                            breadcrumbs=build_breadcrumbs(subpath),
                            current_path=subpath)
    
    # 检查是否是文本文件
    if os.path.isfile(current_path) and is_text_file(os.path.basename(current_path)):
        return view_text_file(subpath)
    
    # 新增HTML库检测逻辑
    if contains_html(current_path):
        # 如果是页面库，直接进入第一个HTML文件的阅览逻辑
        first_html_file = get_first_html_file(current_path)
        if first_html_file:
            # 构建完整的HTML文件路径
            html_filepath = os.path.join(subpath, first_html_file).replace('\\', '/')
            # 重定向到handle_html_file函数处理
            return redirect(url_for('handle_html_file', filepath=html_filepath))
        
        # 如果没有找到HTML文件，回退到原来的展示逻辑
        return render_template('html_gallery.html',
                         items=build_html_items(current_path, subpath),
                         breadcrumbs=build_breadcrumbs(subpath),
                         folder=subpath)
    
    # 使用build_directory_items函数构建目录项（这会应用漫画模式排序）
    items = build_directory_items(current_path, subpath)
    
    # 生成面包屑导航
    breadcrumbs = build_breadcrumbs(subpath)
    
    return render_template('index.html', 
                         items=items,
                         breadcrumbs=breadcrumbs,
                         current_path=subpath)

# 图片库逻辑。
@app.route('/')
def index():
    # if not is_windows_client():
    #     abort(404)  # 非Windows客户端返回404
    #     return
    return browse_directory('')

@app.route('/text/<path:filepath>')
def view_text_file(filepath):
    """查看文本文件内容"""
    file_path = os.path.join(SHARE_DIR, filepath)
    
    if not os.path.exists(file_path):
        abort(404)
    
    filename = os.path.basename(filepath)
    file_ext = os.path.splitext(filename)[1].lower()
    
    content = ""
    
    # 处理不同类型的文件
    if file_ext == '.pdf' and HAS_PYPDF2:
        # 处理PDF文件
        try:
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                content = ""
                for page in pdf_reader.pages:
                    content += page.extract_text() + "\n\n"
            # 简单的格式处理
            content = content.replace("\n\n", "</p><p>").replace("\n", "<br>")
            content = f"<p>{content}</p>"
        except Exception as e:
            content = f"<p>无法读取PDF文件: {str(e)}</p>"
    elif file_ext == '.docx' and HAS_DOCX:
        # 处理DOCX文件
        try:
            import re  # 添加正则表达式导入
            doc = Document(file_path)
            content = ""
            for paragraph in doc.paragraphs:
                text = paragraph.text
                style = paragraph.style.name if paragraph.style else ""

                # 使用正则匹配所有Heading级别（1-6）
                heading_match = re.match(r'^Heading (\d+)$', style)
                if heading_match:
                    level = int(heading_match.group(1))
                    if 1 <= level <= 6:
                        content += f"<h{level}>{text}</h{level}>"
                elif style.startswith('List'):
                    content += f"<li>{text}</li>"
                else:
                    # 普通段落
                    if text.strip():
                        content += f"<p>{text}</p>"
                    else:
                        content += "<br>"
        except Exception as e:
            content = f"<p>无法读取DOCX文件: {str(e)}</p>"
    else:
        # 处理纯文本文件
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # 简单的文本格式化
            content = content.replace("\n\n", "</p><p>").replace("\n", "<br>")
            content = f"<p>{content}</p>"
        except UnicodeDecodeError:
            # 如果UTF-8解码失败，尝试其他编码
            try:
                with open(file_path, 'r', encoding='gbk') as f:
                    content = f.read()
                content = content.replace("\n\n", "</p><p>").replace("\n", "<br>")
                content = f"<p>{content}</p>"
            except Exception:
                content = "<p>文件编码不支持或文件已损坏</p>"
        except Exception as e:
            content = f"<p>无法读取文件: {str(e)}</p>"
    
    return render_template('text_viewer.html', 
                         content=content, 
                         filename=filename,
                         filepath=filepath)

@app.route('/gallery/<path:folder>')
def show_gallery(folder):
    gallery_path = os.path.join(SHARE_DIR, folder)

    # 先检查是否是页面库（至少包含一个HTML文件，可能包含ServerData文件夹）
    # 检查是否包含HTML文件
    has_html = any(is_html_file(f) for f in os.listdir(gallery_path))
    
    # 如果是页面库，直接打开第一个HTML文件
    if has_html:
        first_html_file = get_first_html_file(gallery_path)
        if first_html_file:
            # 构建完整的HTML文件路径
            html_filepath = os.path.join(folder, first_html_file).replace('\\', '/')
            # 重定向到handle_html_file函数处理
            return redirect(url_for('handle_html_file', filename=html_filepath))
    
    # 先检查是否存在子目录
    if any(os.path.isdir(os.path.join(gallery_path, f)) for f in os.listdir(gallery_path)):
        return browse_directory(folder)  # 返回目录浏览视图
    
    all_files = os.listdir(gallery_path)
    images = [f for f in all_files if is_image_file(f)]
    videos = [f for f in all_files if is_video_file(f)]
    texts = [f for f in all_files if is_text_file(f)]
    htmls = [f for f in all_files if is_html_file(f)]
    
    # 添加空文件夹检查
    if not images and not videos and not texts:
        abort(404, description="该文件夹没有可显示的媒体文件")
    
    # 添加总数保护
    total_count = max(len(images), len(videos), len(texts), 1)  # 确保最小值1
    
    if videos and not images and not texts:
        return render_template('video_gallery.html',
                            files=sorted(videos),
                            folder=folder,
                            current=get_position(request),
                            total=total_count)
    
    if (texts or htmls) and not images and not videos:
        return render_template('text_gallery.html',
                            files=sorted(texts),
                            folder=folder,
                            current=get_position(request),
                            total=total_count)
    
    # 获取间隔参数，仅对图片库有效
    interval = 0
    total_original = len(images)
    filtered_images = images  # 默认使用所有图片
    
    # 获取URL中的间隔参数
    interval_param = request.args.get('interval', '0')
    try:
        interval = max(0, int(interval_param))  # 确保interval是非负整数
    except ValueError:
        interval = 0
    
    # 标记是否使用了位置过滤
    use_position_filter = False
    
    # 处理固定位置起始加载
    start_pos_param = request.args.get('start_pos')
    count_param = request.args.get('count')
    
    # 先确定起始位置和数量，然后再应用间隔
    if start_pos_param and count_param:
        try:
            start_pos = max(0, int(start_pos_param))
            count = max(1, int(count_param))
            
            # 确保起始位置不超过图片总数
            start_pos = min(start_pos, len(images) - 1)
            
            if interval > 0:
                # 如果有间隔参数，计算符合条件的图片（从start_pos开始，每隔interval+1张取一张）
                step = interval + 1
                # 计算实际需要的图片数量（考虑间隔后需要更多的原始图片）
                needed_images = start_pos + count * step
                # 确保不超出原始图片范围
                needed_images = min(needed_images, len(images))
                
                # 从start_pos开始，每隔step张取一张，共取count张
                filtered_images = [images[i] for i in range(start_pos, needed_images, step)][:count]
                use_position_filter = True
            else:
                # 没有间隔参数，直接截取指定范围
                end_pos = min(start_pos + count, len(images))
                filtered_images = images[start_pos:end_pos]
                use_position_filter = True
        except ValueError:
            # 参数无效，使用原始列表
            filtered_images = images
            interval = 0
    else:
        # 没有指定起始位置和数量，但有间隔参数
        if interval > 0:
            # 按照每interval+1张图片发送一张的规则
            filtered_images = [images[i] for i in range(len(images)) if i % (interval + 1) == 0]
            
            # 如果过滤后没有图片，则使用原始列表
            if not filtered_images:
                filtered_images = images
                interval = 0
    
    # 处理百分比位置起始加载
    start_percent_param = request.args.get('start_percent')
    percent_count_param = request.args.get('percent_count')
    
    # 只有当没有使用固定位置起始加载时才应用百分比起始加载
    if start_percent_param and percent_count_param and not (start_pos_param and count_param):
        try:
            start_percent = max(0, min(100, int(start_percent_param)))
            count = max(1, int(percent_count_param))
            
            # 计算起始位置
            start_pos = int(len(images) * start_percent / 100)
            start_pos = min(start_pos, len(images) - 1)
            
            if interval > 0:
                # 如果有间隔参数，计算符合条件的图片
                step = interval + 1
                # 计算实际需要的图片数量
                needed_images = start_pos + count * step
                needed_images = min(needed_images, len(images))
                
                # 从start_pos开始，每隔step张取一张
                filtered_images = [images[i] for i in range(start_pos, needed_images, step)][:count]
                use_position_filter = True
            else:
                # 没有间隔参数，直接截取指定范围
                end_pos = min(start_pos + count, len(images))
                filtered_images = images[start_pos:end_pos]
                use_position_filter = True
        except ValueError:
            # 参数无效，使用原始列表
            filtered_images = images
            interval = 0
    
    # 获取当前位置
    current_position = get_position(request)
    total_count = len(filtered_images)
    
    # 传递是否使用了位置过滤的标志
    return render_template('gallery.html',
                         images=sorted(filtered_images),
                         folder=folder,
                         current=current_position,
                         total=total_count,
                         total_original=total_original,  # 传递原始总数量
                         interval=interval,  # 传递当前使用的间隔参数
                         use_position_filter=use_position_filter)  # 新增：是否使用了位置过滤

@app.route('/ServerData/<path:filepath>')
def serve_server_data(filepath):
    # 构建完整的ServerData文件路径
    # filepath现在包含了HTML所在目录和文件名，如：path/to/html/2_1.jpg
    server_data_path = os.path.join(SHARE_DIR, filepath)
    
    # 确保路径安全，防止目录遍历攻击
    server_data_dir = os.path.abspath(SHARE_DIR)
    requested_path = os.path.abspath(server_data_path)
    
    # 验证请求的文件是否在允许的目录内，并且文件确实存在
    if (os.path.exists(requested_path) and os.path.isfile(requested_path) and
        requested_path.startswith(server_data_dir) and
        'ServerData' in requested_path.split(os.sep)):
        return send_file(requested_path, mimetype='image/jpeg')
    
    # 如果找不到文件或路径不安全，返回404错误
    print(f"未找到ServerData图片或路径不安全: {filepath}")
    abort(404)

# 如果需要额外的静态文件路由，可以添加以下代码
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)


# ===== 聚合搜索 =====

def _safe_within_share(target_rel):
    """将相对路径解析为绝对路径，并校验其位于 SHARE_DIR 之内。返回 (abs_path, share_abs) 或 None。"""
    share_abs = os.path.abspath(SHARE_DIR)
    abs_path = os.path.abspath(os.path.join(SHARE_DIR, target_rel)) if target_rel else share_abs
    if abs_path == share_abs or abs_path.startswith(share_abs + os.sep):
        return abs_path, share_abs
    return None


@app.route('/aggsearch/create')
def aggsearch_create():
    """以 root 为根递归搜索视频文件名，匹配后在其下创建持久化的聚合搜索目录。"""
    root = request.args.get('root', '')
    query = request.args.get('q', '').strip()
    case_sensitive = request.args.get('case_sensitive', 'false').lower() == 'true'
    whole_word = request.args.get('whole_word', 'false').lower() == 'true'

    if not query:
        return jsonify({'success': False, 'error': '请输入搜索关键词'})

    safe = _safe_within_share(root)
    if not safe:
        return jsonify({'success': False, 'error': '非法路径'})
    root_full, _ = safe
    if not os.path.isdir(root_full):
        return jsonify({'success': False, 'error': '根目录不存在'})

    matches = find_matching_videos(root_full, query, case_sensitive, whole_word)

    if not matches:
        return jsonify({'success': True, 'count': 0})

    agg_path = create_aggsearch_dir(root, query, case_sensitive, whole_word, matches)
    return jsonify({'success': True, 'count': len(matches), 'path': agg_path})


@app.route('/aggsearch/delete')
def aggsearch_delete():
    """删除一个聚合搜索目录（仅删除索引目录，不影响原始视频文件）。"""
    agg_path = request.args.get('path', '')
    safe = _safe_within_share(agg_path)
    if not safe:
        return jsonify({'success': False, 'error': '非法路径'})
    agg_full, _ = safe
    if not os.path.isdir(agg_full):
        return jsonify({'success': False, 'error': '目录不存在'})
    if not is_aggsearch_dir(os.path.basename(agg_full)):
        return jsonify({'success': False, 'error': '非聚合搜索目录'})
    try:
        shutil.rmtree(agg_full)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    return jsonify({'success': True})


@app.route('/aggview/<path:aggdir>')
def aggview(aggdir):
    """查看聚合搜索目录：读取 index.json，以视频库形式展示匹配到的视频。"""
    safe = _safe_within_share(aggdir)
    if not safe:
        abort(403)
    agg_full, _ = safe
    if not os.path.isdir(agg_full) or not is_aggsearch_dir(os.path.basename(agg_full)):
        abort(404)
    index_file = os.path.join(agg_full, 'index.json')
    if not os.path.isfile(index_file):
        abort(404)
    with open(index_file, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    files = meta.get('files', [])
    return render_template('video_gallery.html',
                           files=sorted(files),
                           folder=aggdir,
                           full_path_mode=True)


# ===== JM 漫画搜索/拉取 =====

try:
    import jm_service
    HAS_JM = True
except ImportError:
    HAS_JM = False

try:
    import pika_service
    HAS_PIKA = True
except ImportError:
    HAS_PIKA = False


@app.route('/jm/search')
def jm_search():
    """站内搜索: q=关键词, page=页码(1起), mode=site|author|work|id,
    order_by=mr|mv|mp|tf, search_type=keyword|fuzzy|exact,
    page_size=10|25|50, source=jm|pic。非法参数回退默认值。"""
    if not HAS_JM:
        return jsonify({'success': False, 'error': 'jmcomic 未安装'})
    query = request.args.get('q', '').strip()
    page = request.args.get('page', '1')
    mode = request.args.get('mode', 'site')
    order_by = request.args.get('order_by', 'mr')
    search_type = request.args.get('search_type', 'keyword')
    page_size = request.args.get('page_size', '25')
    source = request.args.get('source', 'jm')
    if not query:
        return jsonify({'success': False, 'error': '请输入搜索关键词'})
    if mode not in ('site', 'author', 'work', 'id'):
        mode = 'site'
    if order_by not in ('mr', 'mv', 'mp', 'tf'):
        order_by = 'mr'
    if search_type not in ('keyword', 'fuzzy', 'exact'):
        search_type = 'keyword'
    try:
        page_size = int(page_size)
    except (TypeError, ValueError):
        page_size = 25
    if page_size not in (10, 25, 50):
        page_size = 25
    if source not in ('jm', 'pic'):
        source = 'jm'
    try:
        result = jm_service.search(query, page, mode, order_by, search_type, page_size, source)
        result['success'] = True
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/jm/cover/<album_id>')
def jm_cover(album_id):
    """封面图代理（缓存于 jm_cover_cache/）。"""
    if not HAS_JM:
        abort(404)
    path = jm_service.cover_path(album_id)
    if path is None:
        abort(404)
    return send_file(path, mimetype='image/jpeg')


@app.route('/jm/download', methods=['POST'])
def jm_download():
    """创建下载任务。body: {aid, title, author, mode: temp|persist}。"""
    if not HAS_JM:
        return jsonify({'success': False, 'error': 'jmcomic 未安装'})
    data = request.get_json(silent=True) or {}
    aid = str(data.get('aid', '')).strip()
    mode = data.get('mode', 'temp')
    if not aid or not aid.isdigit():
        return jsonify({'success': False, 'error': '无效的 album id'})
    if mode not in ('temp', 'persist'):
        mode = 'temp'
    try:
        tid = jm_service.start_download(aid, data.get('title', ''), data.get('author', ''), mode)
        return jsonify({'success': True, 'tid': tid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/jm/status')
def jm_status():
    """查询下载任务状态: tid。"""
    if not HAS_JM:
        return jsonify({'success': False, 'error': 'jmcomic 未安装'})
    tid = request.args.get('tid', '')
    task = jm_service.task_status(tid)
    if task is None:
        return jsonify({'success': False, 'error': '任务不存在'})
    task['success'] = True
    return jsonify(task)


@app.route('/jm/online')
def jm_online():
    """在线阅读入口: 预置占位文件, 返回 /gallery 路径。aid=album_id。"""
    if not HAS_JM:
        return jsonify({'success': False, 'error': 'jmcomic 未安装'})
    aid = request.args.get('aid', '').strip()
    if not aid.isdigit():
        return jsonify({'success': False, 'error': '无效的 album id'})
    try:
        return jsonify({'success': True, **jm_service.prepare_online(aid)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/jm/persist', methods=['POST'])
def jm_persist():
    """把 temp 阅读缓存持久化到 share 根目录(移动语义)。
    body: {path: temp/<作者> 或 temp/<作者>/<标题>}。"""
    if not HAS_JM:
        return jsonify({'success': False, 'error': 'jmcomic 未安装'})
    data = request.get_json(silent=True) or {}
    path = str(data.get('path', '')).strip()
    if not path:
        return jsonify({'success': False, 'error': '缺少 path 参数'})
    try:
        result = jm_service.persist_temp(path)
        return jsonify({'success': True, **result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/jm/check')
def jm_check():
    """检查专辑下载状态: aid=album_id。
    返回 {downloaded, path, in_temp, temp_path}。"""
    if not HAS_JM:
        return jsonify({'success': False, 'error': 'jmcomic 未安装'})
    aid = request.args.get('aid', '').strip()
    if not aid.isdigit():
        return jsonify({'success': False, 'error': '无效的 album id'})
    try:
        return jsonify({'success': True, **jm_service.check_album(aid)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/jm/config', methods=['GET', 'POST'])
def jm_config():
    """配置读写: GET 返回 {temp_retention_days};
    POST {temp_retention_days: N} 保存(1-90, 非法回退默认 7)。"""
    if not HAS_JM:
        return jsonify({'success': False, 'error': 'jmcomic 未安装'})
    if request.method == 'GET':
        return jsonify({'success': True, 'temp_retention_days':
                        jm_service._config_get('temp_retention_days',
                                               jm_service.DEFAULT_TEMP_RETENTION_DAYS)})
    data = request.get_json(silent=True) or {}
    try:
        n = int(data.get('temp_retention_days'))
    except (TypeError, ValueError):
        n = jm_service.DEFAULT_TEMP_RETENTION_DAYS
    if not (1 <= n <= 90):
        n = jm_service.DEFAULT_TEMP_RETENTION_DAYS
    jm_service._config_set('temp_retention_days', n)
    return jsonify({'success': True, 'temp_retention_days': n})


@app.route('/jm/reader/<album_id>')
def jm_reader(album_id):
    """在线懒加载阅读页。"""
    if not HAS_JM:
        abort(404)
    try:
        info = jm_service.album_chapters(album_id)
    except Exception as e:
        return f'获取漫画信息失败: {e}', 500
    return render_template('jm_reader.html',
                           album_id=info['id'],
                           title=info['title'],
                           author=info['author'],
                           chapters=info['chapters'])


@app.route('/jm/chapters')
def jm_chapters():
    """章节列表: aid=album_id。"""
    if not HAS_JM:
        return jsonify({'success': False, 'error': 'jmcomic 未安装'})
    aid = request.args.get('aid', '').strip()
    if not aid.isdigit():
        return jsonify({'success': False, 'error': '无效的 album id'})
    try:
        return jsonify({'success': True, **jm_service.album_chapters(aid)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/jm/pages')
def jm_pages():
    """章节页数: aid=album_id, pid=photo_id。"""
    if not HAS_JM:
        return jsonify({'success': False, 'error': 'jmcomic 未安装'})
    aid = request.args.get('aid', '').strip()
    pid = request.args.get('pid', '').strip()
    if not aid.isdigit() or not pid.isdigit():
        return jsonify({'success': False, 'error': '无效的 id'})
    try:
        return jsonify({'success': True, **jm_service.chapter_pages(aid, pid)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/jm/page')
def jm_page():
    """按需物化并返回单张图片: aid, pid, index(1起)。"""
    if not HAS_JM:
        abort(404)
    aid = request.args.get('aid', '').strip()
    pid = request.args.get('pid', '').strip()
    index = request.args.get('index', '')
    if not aid.isdigit() or not pid.isdigit() or not index.isdigit():
        abort(404)
    try:
        path = jm_service.fetch_page(aid, pid, int(index))
    except IndexError:
        abort(404)
    except Exception as e:
        return f'图片获取失败: {e}', 500
    return send_file(path)


# ===== Pika (PicACG) 搜索/拉取 =====

def _pika_unavailable():
    return jsonify({'success': False, 'error': 'pika_service 未安装或未就绪'})


@app.route('/pika/search')
def pika_search():
    """站内搜索: q=关键词, page=页码(1起), mode=site|author|work|id,
    order_by=mr|mv|mp|tf, search_type=keyword|fuzzy|exact,
    page_size=10|25|50。非法参数回退默认值。"""
    if not HAS_PIKA:
        return _pika_unavailable()
    query = request.args.get('q', '').strip()
    page = request.args.get('page', '1')
    mode = request.args.get('mode', 'site')
    order_by = request.args.get('order_by', 'mr')
    search_type = request.args.get('search_type', 'keyword')
    page_size = request.args.get('page_size', '25')
    if not query:
        return jsonify({'success': False, 'error': '请输入搜索关键词'})
    if mode not in ('site', 'author', 'work', 'id'):
        mode = 'site'
    if order_by not in ('mr', 'mv', 'mp', 'tf'):
        order_by = 'mr'
    if search_type not in ('keyword', 'fuzzy', 'exact'):
        search_type = 'keyword'
    try:
        page_size = int(page_size)
    except (TypeError, ValueError):
        page_size = 25
    if page_size not in (10, 25, 50):
        page_size = 25
    try:
        result = pika_service.search(query, page, mode, order_by, search_type, page_size)
        result['success'] = True
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/pika/cover/<book_id>')
def pika_cover(book_id):
    """封面图代理。"""
    if not HAS_PIKA:
        abort(404)
    try:
        path = pika_service.cover(book_id)
    except Exception:
        abort(404)
    if not path:
        abort(404)
    return send_file(path, mimetype='image/jpeg')


@app.route('/pika/download', methods=['POST'])
def pika_download():
    """创建下载任务。body: {aid, title, author, mode: temp|persist}。"""
    if not HAS_PIKA:
        return _pika_unavailable()
    data = request.get_json(silent=True) or {}
    aid = str(data.get('aid', '')).strip()
    mode = data.get('mode', 'temp')
    if not aid:
        return jsonify({'success': False, 'error': '无效的 book id'})
    if mode not in ('temp', 'persist'):
        mode = 'temp'
    try:
        tid = pika_service.start_download(aid, data.get('title', ''), data.get('author', ''), mode)
        return jsonify({'success': True, 'tid': tid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/pika/status')
def pika_status():
    """查询下载任务状态: tid。"""
    if not HAS_PIKA:
        return _pika_unavailable()
    tid = request.args.get('tid', '')
    try:
        task = pika_service.task_status(tid)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    if task is None:
        return jsonify({'success': False, 'error': '任务不存在'})
    task['success'] = True
    return jsonify(task)


@app.route('/pika/online')
def pika_online():
    """在线阅读入口: 预置占位文件, 返回 gallery 路径。aid/book_id。"""
    if not HAS_PIKA:
        return _pika_unavailable()
    book_id = (request.args.get('aid') or request.args.get('book_id') or '').strip()
    if not book_id:
        return jsonify({'success': False, 'error': '无效的 book id'})
    try:
        return jsonify({'success': True, **pika_service.prepare_online(book_id)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/pika/check')
def pika_check():
    """检查专辑下载状态: aid/book_id。
    返回 {downloaded, path, in_temp, temp_path}。"""
    if not HAS_PIKA:
        return _pika_unavailable()
    book_id = (request.args.get('aid') or request.args.get('book_id') or '').strip()
    if not book_id:
        return jsonify({'success': False, 'error': '无效的 book id'})
    try:
        return jsonify({'success': True, **pika_service.check_album(book_id)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/pika/persist', methods=['POST'])
def pika_persist():
    """把 temp 阅读缓存持久化到 share 根目录(移动语义)。
    body: {path: temp/<作者> 或 temp/<作者>/<标题>}。"""
    if not HAS_PIKA:
        return _pika_unavailable()
    data = request.get_json(silent=True) or {}
    path = str(data.get('path', '')).strip()
    if not path:
        return jsonify({'success': False, 'error': '缺少 path 参数'})
    try:
        result = pika_service.persist_temp(path)
        return jsonify({'success': True, **result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/pika/config')
def pika_config():
    """读取配置: 返回 {email_set}。"""
    if not HAS_PIKA:
        return _pika_unavailable()
    try:
        cfg = pika_service.get_config()
        return jsonify({'success': True, **cfg})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ===== 双源合并搜索 =====

@app.route('/search')
def merged_search():
    """双源合并搜索: source=jm|pika|all(默认 all),
    其余参数同 /jm/search。source=all 并行查 jm+pika,
    items 合并(各带 source 字段), pika 失败不阻断 jm。
    返回 {success, total, page, items, pika_error?}。"""
    query = request.args.get('q', '').strip()
    page = request.args.get('page', '1')
    mode = request.args.get('mode', 'site')
    order_by = request.args.get('order_by', 'mr')
    search_type = request.args.get('search_type', 'keyword')
    page_size = request.args.get('page_size', '25')
    source = request.args.get('source', 'all')
    if not query:
        return jsonify({'success': False, 'error': '请输入搜索关键词'})
    if source not in ('jm', 'pika', 'all'):
        source = 'all'
    if mode not in ('site', 'author', 'work', 'id'):
        mode = 'site'
    if order_by not in ('mr', 'mv', 'mp', 'tf'):
        order_by = 'mr'
    if search_type not in ('keyword', 'fuzzy', 'exact'):
        search_type = 'keyword'
    try:
        page_size = int(page_size)
    except (TypeError, ValueError):
        page_size = 25
    if page_size not in (10, 25, 50):
        page_size = 25

    if source == 'jm':
        if not HAS_JM:
            return jsonify({'success': False, 'error': 'jmcomic 未安装'})
        try:
            result = jm_service.search(query, page, mode, order_by, search_type, page_size)
            result['items'] = [dict(it, source='jm') for it in result.get('items', [])]
            result['success'] = True
            return jsonify(result)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    if source == 'pika':
        if not HAS_PIKA:
            return _pika_unavailable()
        try:
            result = pika_service.search(query, page, mode, order_by, search_type, page_size)
            result['success'] = True
            return jsonify(result)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    # source == 'all': 并行查 jm+pika, pika 失败不阻断 jm
    jm_items, jm_total = [], 0
    if HAS_JM:
        try:
            jr = jm_service.search(query, page, mode, order_by, search_type, page_size)
            jm_items = [dict(it, source='jm') for it in jr.get('items', [])]
            jm_total = jr.get('total', 0)
        except Exception as e:
            jm_items, jm_total = [], 0

    pika_items, pika_total = [], 0
    pika_error = None
    if HAS_PIKA:
        try:
            pr = pika_service.search(query, page, mode, order_by, search_type, page_size)
            pika_items = [dict(it, source='pika') for it in pr.get('items', [])]
            pika_total = pr.get('total', 0)
        except Exception as e:
            pika_items, pika_total = [], 0
            pika_error = str(e)

    if not HAS_JM and not HAS_PIKA:
        return jsonify({'success': False, 'error': 'jmcomic 与 pika_service 均未安装'})

    return jsonify({
        'success': True,
        'total': jm_total + pika_total,
        'page': page,
        'items': jm_items + pika_items,
        'pika_error': pika_error,
    })