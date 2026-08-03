import os
from flask import Flask

# 获取当前文件所在的目录
current_dir = os.path.dirname(os.path.abspath(__file__))
# 静态文件目录设置为 CustomRoute 目录的父目录下的 src 文件夹
static_folder_path = os.path.join(current_dir, '..', 'src')

app = Flask(__name__, static_folder=static_folder_path, static_url_path='/static')

from .BaseRoute import *
from .ServiceRoute import *
from .SequenceRoute import *

# 定义包的公共接口
__all__ = [
    'app',      # 路由针对的Flask应用实例

    # 所有的自定义路由应该放在这个位置。
    'BaseRoute',
    'ServiceRoute', 
    'SequenceRoute'
]

