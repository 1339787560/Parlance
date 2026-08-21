import os
import requests
from bs4 import BeautifulSoup
import re
import time
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class LaiManHuaDownloader:
    def __init__(self, config_path="./spider/config.yaml"):
        # 创建带重试机制的session
        self.session = requests.Session()
        
        # 设置重试策略
        retry_strategy = Retry(
            total=3,  # 总重试次数
            backoff_factor=1,  # 退避因子
            status_forcelist=[429, 500, 502, 503, 504],  # 需要重试的状态码
        )
        
        # 创建适配器并挂载到session
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # 加载配置文件
        self.config = self._load_config(config_path)
        
        # 设置请求头
        headers = self.config.get('headers', {})
        if headers:
            self.session.headers.update(headers)
        else:
            # 默认请求头
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })
        
        # 设置基础URL
        self.base_url = self.config.get('laimanhua_base_url', 'https://www.laimanhua.org')
    
    def _load_config(self, config_path):
        """加载YAML配置文件"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            print(f"配置文件 {config_path} 不存在，使用默认配置")
            return {}
        except Exception as e:
            print(f"加载配置文件时出错: {e}，使用默认配置")
            return {}
        
    def get_comic_title(self, html_content):
        """从HTML内容中提取漫画标题"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 尝试多种方式提取标题
        title_selectors = [
            '.detail-info-title h1',  # laimanhua网站可能使用的标题选择器
            '.book-title h1',         # 可能的另一个选择器
            'h1.title',               # 通用标题选择器
            'title'                   # 从页面标题中提取
        ]
        
        for selector in title_selectors:
            title_element = soup.select_one(selector)
            if title_element:
                title = title_element.get_text(strip=True)
                if title and len(title) > 0:
                    # 清理标题中的非法字符
                    title = re.sub(r'[<>:"/\\|?*]', '', title)
                    return title
        
        # 如果以上方法都没找到，尝试从文本中提取
        text = soup.get_text()
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if line and len(line) < 50:  # 假设标题不会太长
                cleaned_line = re.sub(r'[<>:"/\\|?*]', '', line)
                if cleaned_line and not cleaned_line.startswith('http'):
                    return cleaned_line
        
        return "未知漫画"
    
    def extract_chapter_links(self, html_content):
        """提取laimanhua网站的章节链接信息"""
        soup = BeautifulSoup(html_content, 'html.parser')
        chapters = []
        seen_names = set()  # 用于跟踪已见过的章节名称
        
        # 根据您提供的信息，章节信息存储在 ul.j-chapter-list 下
        chapter_list = soup.find('ul', class_='j-chapter-list')
        
        if chapter_list:
            # 遍历 ul.j-chapter-list 下的所有章节
            links = chapter_list.find_all('a')
            
            for link in links:
                # 提取章节名称
                chapter_name = link.get_text(strip=True)
                
                if chapter_name:
                    # 清理章节名称中的非法字符
                    chapter_name = re.sub(r'[<>:"/\\|?*]', '', chapter_name)
                    
                    # 检查是否已经处理过同名章节（去重）
                    if chapter_name in seen_names:
                        continue  # 跳过重复章节
                    
                    # 提取章节链接
                    chapter_url = link.get('href')
                    if chapter_url:
                        # 确保URL是完整的
                        if not chapter_url.startswith(('http://', 'https://')):
                            chapter_url = urljoin(self.base_url, chapter_url)
                        
                        chapters.append({
                            'name': chapter_name,
                            'url': chapter_url
                        })
                        seen_names.add(chapter_name)  # 记录已处理的章节名称
        
        return chapters
    
    def download_chapter_images(self, chapter_url, chapter_folder):
        """下载章节图片，根据您提供的信息，从 div.imgbox 获取图片"""
        downloaded_count = 0
        
        try:
            print(f"正在处理章节: {chapter_url}")
            
            # 从配置文件获取超时设置，默认为10秒
            timeout = self.config.get('request_timeout', 10)
            
            response = self.session.get(chapter_url, timeout=timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # 根据您提供的信息，查找 div.imgbox 中的图片
            images = []
            
            # 查找漫画阅读区域中的图片
            imgbox = soup.find('div', class_='imgbox')
            if imgbox:
                img_tags = imgbox.find_all('img')
                for i, img in enumerate(img_tags):
                    # 获取图片的真实地址，可能是 src 或 data-src 属性
                    src = img.get('src') or img.get('data-src') or img.get('data-original')
                    if src:
                        images.append({
                            'url': src,
                            'name': f"{i + 1:03d}"  # 使用顺序编号命名
                        })
            else:
                # 如果没有找到 imgbox，尝试其他选择器
                print(f"警告: 在页面 {chapter_url} 中未找到 .imgbox 元素")
                # 备用方案：查找其他可能的图片容器
                comic_container = soup.find('div', id='images') or soup.find('div', class_=re.compile(r'comic-content|reader-content|comic-contain'))
                if comic_container:
                    img_tags = comic_container.find_all('img')
                    for i, img in enumerate(img_tags):
                        src = img.get('src') or img.get('data-src') or img.get('data-original')
                        if src:
                            images.append({
                                'url': src,
                                'name': f"{i + 1:03d}"  # 使用顺序编号命名
                            })
            
            # 去重并过滤无效链接
            valid_images = [img for img in images if img['url']]
            if not valid_images:
                print(f"未在页面 {chapter_url} 中找到图片")
            else:
                # 下载图片
                for img_info in valid_images:
                    img_url = img_info['url']
                    img_name = img_info['name']
                    
                    try:
                        # 确保图片URL完整
                        if not img_url.startswith(('http://', 'https://')):
                            img_url = urljoin(self.base_url, img_url)
                        
                        img_response = self.session.get(img_url, stream=True)
                        img_response.raise_for_status()
                        
                        # 确定文件扩展名
                        content_type = img_response.headers.get('content-type', '')
                        if 'jpeg' in content_type or 'jpg' in content_type:
                            ext = '.jpg'
                        elif 'png' in content_type:
                            ext = '.png'
                        elif 'gif' in content_type:
                            ext = '.gif'
                        elif 'webp' in content_type:
                            ext = '.webp'
                        else:
                            # 从URL中猜测扩展名
                            parsed = urlparse(img_url)
                            ext = os.path.splitext(parsed.path)[1]
                            if not ext:
                                ext = '.jpg'
                        
                        # 保存图片，使用顺序编号命名
                        filename = f"{img_name}{ext}"
                        filepath = os.path.join(chapter_folder, filename)
                        
                        # 检查文件是否已存在，避免重复下载
                        if os.path.exists(filepath):
                            print(f"  图片 {filename} 已存在，跳过")
                            continue
                        
                        with open(filepath, 'wb') as f:
                            for chunk in img_response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        
                        downloaded_count += 1
                        print(f"  下载图片 {filename}")
                        
                        # 从配置文件获取图片间延迟
                        image_delay = self.config.get('download_delay', {}).get('between_images', 0.5)
                        time.sleep(image_delay)  # 礼貌延迟
                        
                    except Exception as e:
                        print(f"  下载图片失败: {e}")
                        continue
        
        except Exception as e:
            print(f"下载章节失败: {e}")
            
        return downloaded_count

    def download_comic(self, url_or_html, output_dir=None):
        """主下载函数"""
        # 判断输入是URL还是HTML内容
        if url_or_html.startswith(('http://', 'https://')):
            print(f"正在访问URL: {url_or_html}")
            response = self.session.get(url_or_html)
            response.raise_for_status()
            html_content = response.text
        else:
            html_content = url_or_html
            print("使用提供的HTML内容")
        
        # 提取漫画标题
        comic_title = self.get_comic_title(html_content)
        print(f"漫画标题: {comic_title}")
        
        # 处理输出目录
        if output_dir:
            # 如果配置了输出目录，使用配置的目录作为根目录，在其下创建以漫画标题命名的文件夹
            base_dir = os.path.join(output_dir, comic_title)
        else:
            # 否则使用默认目录
            base_dir = os.path.join(os.getcwd(), comic_title)
        
        # 如果输出目录是相对路径，转换为绝对路径
        if not os.path.isabs(base_dir):
            base_dir = os.path.abspath(base_dir)
        
        # 确保输出目录存在
        os.makedirs(base_dir, exist_ok=True)
        print(f"保存到: {base_dir}")
        
        # 提取章节信息
        chapters = self.extract_chapter_links(html_content)
        print(f"找到 {len(chapters)} 个章节")
        
        # 从配置文件获取最大线程数
        max_threads = self.config.get('max_threads', 5)
        max_workers = min(max_threads, len(chapters))
        
        # 使用线程池并发下载章节
        completed_chapters = 0
        total_downloaded = 0
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有章节下载任务
            future_to_chapter = {
                executor.submit(self._download_single_chapter, chapter, base_dir): chapter 
                for chapter in chapters
            }
            
            # 处理完成的任务
            for future in as_completed(future_to_chapter):
                chapter = future_to_chapter[future]
                try:
                    downloaded = future.result()
                    completed_chapters += 1
                    total_downloaded += downloaded
                    print(f"章节 {chapter['name']} 完成, 下载了 {downloaded} 张图片")
                except Exception as e:
                    completed_chapters += 1
                    print(f"章节 {chapter['name']} 下载失败: {e}")
        
        print(f"\n下载完成! 总共下载了 {total_downloaded} 张图片")
        return base_dir
    
    def _download_single_chapter(self, chapter, base_dir):
        """下载单个章节的内部方法，用于线程执行"""
        print(f"\n正在处理章节: {chapter['name']}")
        
        # 创建章节文件夹
        chapter_folder = os.path.join(base_dir, chapter['name'])
        os.makedirs(chapter_folder, exist_ok=True)
        
        # 下载图片
        downloaded = self.download_chapter_images(chapter['url'], chapter_folder)
        
        # 从配置文件获取章节间延迟
        chapter_delay = self.config.get('download_delay', {}).get('between_chapters', 1)
        time.sleep(chapter_delay)
        
        return downloaded

def main():
    # 创建下载器实例，自动加载配置文件
    downloader = LaiManHuaDownloader()
    
    # 从配置文件获取漫画URL列表
    comic_urls = downloader.config.get('laimanhua_comic_urls', [])
    
    # 从配置文件获取输出目录设置
    output_dir = downloader.config.get('output_dir', None)
    
    # 如果没有配置URL，则使用默认URL
    if not comic_urls:
        comic_urls = ["https://www.laimanhua.org/kanmanhua/418438"]
    
    # 下载所有配置的漫画
    for url in comic_urls:
        try:
            print(f"开始下载漫画: {url}")
            downloader.download_comic(url, output_dir)
        except Exception as e:
            print(f"下载漫画 {url} 时出错: {e}")

if __name__ == "__main__":
    main()