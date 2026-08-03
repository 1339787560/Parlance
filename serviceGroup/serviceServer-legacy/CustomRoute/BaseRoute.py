# API路由
from . import app
from flask import render_template
import json
import os


def load_toolbar_config():
    """加载 toolbar 按钮配置"""
    config_path = os.path.join(os.getcwd(), 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return config.get('toolbarButtons', {
                'svnUpdate': True,
                'configModify': True,
                'serverStatus': True,
                'setCurrency': True,
                'downloadLog': True,
                'aiManager': False,
                'ragQA': True,
                'themeToggle': True
            })
    except:
        return {
            'svnUpdate': True,
            'configModify': True,
            'serverStatus': True,
            'setCurrency': True,
            'downloadLog': True,
            'aiManager': False,
            'ragQA': True,
            'themeToggle': True
        }


# 进入主页面
@app.route('/')
def index():
    toolbar_config = load_toolbar_config()
    return render_template('index.html', toolbar_buttons=toolbar_config)

# 进入服务序列管理页面
@app.route('/sequence')
def sequence():
    return render_template('sequence.html')