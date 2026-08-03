import threading
import time
from Service import *
from JsonConfigParser import *
# 修改保存脚本的函数，支持新格式
from flask import jsonify, request
from . import app


@app.route('/api/script/save', methods=['POST'])
def api_save_script():
    try:
        data = request.json
        sequence_name = data.get('name')
        start_order = data.get('start_order')
        
        if not sequence_name or not start_order:
            return jsonify({'success': False, 'message': '参数不完整'}), 400
        
        # 读取现有脚本
        script = read_script()
        
        # 确保scripts字段存在且为数组
        if 'scripts' not in script or not isinstance(script['scripts'], list):
            script['scripts'] = []
        
        # 检查是否已存在同名序列
        existing_index = None
        for i, item in enumerate(script['scripts']):
            if item.get('name') == sequence_name:
                existing_index = i
                break
        
        # 构建新的序列对象
        new_sequence = {
            'name': sequence_name,
            'sequence': start_order,
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # 更新或添加序列
        if existing_index is not None:
            script['scripts'][existing_index] = new_sequence
        else:
            script['scripts'].append(new_sequence)
        
        # 保存脚本文件
        save_script(script)
        
        return jsonify({'success': True, 'message': '序列保存成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存序列时发生错误: {str(e)}'}), 500

# 修改api_execute_named_sequence函数，确保已启动服务被正确处理
@app.route('/api/script/execute/<sequence_name>', methods=['POST'])
def api_execute_named_sequence(sequence_name):
    try:
        # 读取script配置
        script_data = read_script()
        
        # 检查scripts字段是否存在且为数组
        if 'scripts' not in script_data or not isinstance(script_data['scripts'], list):
            return jsonify({'success': False, 'message': '未找到序列配置'}), 404
        
        # 查找指定名称的序列
        sequence_item = next((item for item in script_data['scripts'] if item.get('name') == sequence_name), None)

        if not sequence_item or 'sequence' not in sequence_item:
            return jsonify({'success': False, 'message': f'启动序列 "{sequence_name}" 不存在'}), 404
        
        # 使用Python的字典访问方式
        service_sequence = sequence_item['sequence']
        
        # 使用现有的/api/services/start-sequence逻辑执行序列
        # 存储执行结果
        results = []
        
        # 依次启动每个服务
        for i, service_data in enumerate(service_sequence):
            # 检查service_data是否为字典类型
            if isinstance(service_data, dict):
                name = service_data.get('name')
                type_name = service_data.get('type')
                exe_name = service_data.get('exe')
                
                if not all([name, type_name, exe_name]):
                    return jsonify({
                        'success': False, 
                        'message': f'序列中第{i+1}个服务的参数不完整',
                        'failed_at': i,
                        'results': results
                    }), 400
                
                # 启动服务 - start_service函数已包含服务已启动检查
                success, message = start_service(name, type_name, exe_name)
                results.append({
                    'name': name,
                    'type': type_name,
                    'success': success,
                    'message': message
                })
            elif isinstance(service_data, str):
                # 尝试处理旧格式的start_order（只包含name的数组）
                # 这是旧格式的start_order
                config = read_config()
                if service_data in config.get('service', {}):
                    for service in config['service'][service_data]:
                        # 启动服务 - start_service函数已包含服务已启动检查
                        success, message = start_service(service_data, service['type'], service['exe'])
                        results.append({
                            'name': service_data,
                            'type': service['type'],
                            'success': success,
                            'message': message
                        })
                        
                        if not success:
                            return jsonify({
                                'success': False,
                                'message': f'服务启动失败: {message}',
                                'failed_at': i,
                                'failed_service': f'{service_data}_{service['type']}',
                                'results': results
                            }), 200
                        
                        time.sleep(2)
                else:
                    return jsonify({
                        'success': False, 
                        'message': f'服务组 {service_data} 不存在',
                        'failed_at': i,
                        'results': results
                    }), 400
                continue
            else:
                return jsonify({
                    'success': False, 
                    'message': f'序列中第{i+1}个服务的数据格式无效',
                    'failed_at': i,
                    'results': results
                }), 400
            
            # 如果启动失败，立即返回结果
            if not success:
                return jsonify({
                    'success': False,
                    'message': f'服务启动失败: {message}',
                    'failed_at': i,
                    'failed_service': f'{name}_{type_name}',
                    'results': results
                }), 200
            
            # 等待一段时间确保服务完全启动
            time.sleep(2)
        
        # 所有服务都成功启动
        return jsonify({
            'success': True,
            'message': '所有服务已成功启动',
            'results': results
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'执行启动序列时发生错误: {str(e)}'}), 500

# 修改读取脚本文件的函数，确保返回符合新格式的数据
@app.route('/api/script/get-all', methods=['GET'])
def api_get_all_scripts():
    try:
        script = read_script()
        # 检查是否是旧格式，如果是则转换为新格式
        if 'scripts' in script and isinstance(script['scripts'], dict):
            # 转换旧格式为新格式
            new_format_scripts = []
            for name, data in script['scripts'].items():
                # 构建新格式的序列对象
                new_format_scripts.append({
                    'name': name,
                    'sequence': data.get('start_order', []),
                    'created_at': data.get('created_at')
                })
            script['scripts'] = new_format_scripts
        # 确保scripts字段存在且为数组
        elif 'scripts' not in script:
            script['scripts'] = []
        return jsonify({'success': True, 'scripts': script['scripts']})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# 修改一键启动所有服务逻辑，支持按指定序列启动
@app.route('/api/script/execute', methods=['POST'])
def api_execute_script():
    try:
        data = request.json
        sequence_name = data.get('name')
        
        if not sequence_name:
            return jsonify({'success': False, 'message': '请提供序列名称'}), 400
        
        # 读取脚本
        script = read_script()
        
        # 检查序列是否存在
        if 'scripts' not in script or sequence_name not in script['scripts']:
            return jsonify({'success': False, 'message': f'序列 {sequence_name} 不存在'}), 404
        
        # 获取序列的启动顺序
        start_order = script['scripts'][sequence_name]['start_order']
        
        # 在新线程中启动服务
        def execute_sequence_thread():
            config = read_config()
            results = []
            
            for name in start_order:
                if name in config['service']:
                    for service in config['service'][name]:
                        success, message = start_service(name, service['type'], service['exe'])
                        results.append(message)
                        # 每个服务之间间隔2秒启动
                        time.sleep(2)
                else:
                    results.append(f"服务组 {name} 不存在")
        
        thread = threading.Thread(target=execute_sequence_thread)
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'message': f'序列 {sequence_name} 开始执行，请稍后查看状态'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500