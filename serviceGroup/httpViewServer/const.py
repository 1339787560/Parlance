# 库根目录:相对服务进程 cwd (托管时 cwd=serviceGroup/httpViewServer, 落服务自身 share/)
SHARE_DIR = "./share"
ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.bmp',".webp"}
ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.gif', '.bmp',".webp"}
ALLOWED_VIDEO_EXT = {'.mp4', '.webm', '.ogg', '.mov'}
# 不再提供对 pdf 页面的支持，因为太慢了。
# , '.pdf'
ALLOWED_TEXT_EXT = {'.txt', '.md', '.log', '.csv', '.json', '.xml', '.py', '.js', '.css', '.docx'}