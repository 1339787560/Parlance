import os
import json

def create_defaultConfig():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    if not os.path.exists(config_path):
        with open(config_path, 'w', encoding='utf-8') as f:
            default_config = {
                'abspath': '',
                'service': {}
            }
            json.dump(default_config, f, ensure_ascii=False, indent=4)

# config.json 的管理操作。
def read_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # 确保abspath以/结尾
    abspath = config.get('abspath', '')
    if abspath and not abspath.endswith('/'):
        abspath += '/'
        config['abspath'] = abspath
    
    return config


def save_config(config):
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

# script.json 的管理操作。
def read_script():
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'script.json')
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        # 如果script.json不存在，返回空配置
        return {}

def save_script(script_data):
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'script.json')
    try:
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(script_data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"保存script.json失败: {str(e)}")
        return False
