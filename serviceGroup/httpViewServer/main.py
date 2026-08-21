import argparse

from route import *
from const import *

app.config['TEMPLATES_AUTO_RELOAD'] = True      # 启用模板自动重载
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0     # 禁用静态文件缓存

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5000, help='listen port')
    args = parser.parse_args()

    if not os.path.exists(SHARE_DIR):
        os.makedirs(SHARE_DIR)

    app.run(
        host='0.0.0.0',
        port=args.port,
        threaded=True,
        debug=False
    )
