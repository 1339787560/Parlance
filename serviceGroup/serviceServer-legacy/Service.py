from JsonConfigParser import *
import os
import threading
import time
import psutil
import win32serviceutil
import win32service
import socket

# 全局状态字典，用于存储服务状态
service_status = {}
lock = threading.Lock()

# 通过可执行文件名，获取进程 进程ID
# 通过可执行文件名，获取进程 进程ID
def get_process_id_by_exe(exe_name, exe_path=None):
    # 提取文件名（不包含扩展名）用于模糊匹配
    exe_base_name = os.path.splitext(exe_name)[0].lower()
    
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            # 尝试多种匹配方式
            # 1. 精确匹配进程名
            if proc.info['name'].lower() == exe_name.lower():
                # 如果提供了exe_path，验证exe路径是否匹配
                if exe_path and proc.info.get('exe'):
                    # 比较exe路径是否一致
                    if os.path.normpath(proc.info['exe']).lower() == os.path.normpath(exe_path).lower():
                        return proc.info['pid']
                    # 或者检查exe路径是否包含期望的exe文件名，并且位于正确的目录下
                    elif exe_name.lower() in proc.info['exe'].lower():
                        # 检查exe路径是否在期望的服务目录下
                        if os.path.dirname(os.path.normpath(exe_path)).lower() in os.path.normpath(proc.info['exe']).lower():
                            return proc.info['pid']
                elif not exe_path:  # 如果没有提供exe_path，就只基于进程名匹配
                    return proc.info['pid']
            
            # 2. 匹配进程名（不包含扩展名）
            if os.path.splitext(proc.info['name'])[0].lower() == exe_base_name:
                # 如果提供了exe_path，验证exe路径是否匹配
                if exe_path and proc.info.get('exe'):
                    if exe_name.lower() in proc.info['exe'].lower():
                        # 检查exe路径是否在期望的服务目录下
                        if os.path.dirname(os.path.normpath(exe_path)).lower() in os.path.normpath(proc.info['exe']).lower():
                            return proc.info['pid']
                elif not exe_path:
                    return proc.info['pid']
            
            # 3. 如果有完整路径，检查路径中是否包含可执行文件名
            if proc.info.get('exe'):
                if exe_name.lower() in proc.info['exe'].lower():
                    # 如果提供了exe_path，做额外验证
                    if exe_path:
                        # 检查exe路径是否在期望的服务目录下
                        if os.path.dirname(os.path.normpath(exe_path)).lower() in os.path.normpath(proc.info['exe']).lower():
                            return proc.info['pid']
                    else:
                        return proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return None

# 获取服务名称
def get_service_display_name(name, type_name):
    # 服务的名称为 "同城游_" + name_type
    return f"同城游_{name}_{type_name}"

# 根据进程PID获取其监听的端口
def get_ports_by_pid(pid):
    """
    根据进程PID获取其监听的端口列表
    """
    ports = []
    try:
        process = psutil.Process(pid)
        connections = process.connections(kind='inet')
        for conn in connections:
            if conn.status == 'LISTEN':
                ports.append(conn.laddr.port)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
    return sorted(list(set(ports)))  # 去重并排序

def get_service_ports(service_exe):
    """
    根据服务的可执行文件名获取其占用的端口
    """
    pid = get_process_id_by_exe(service_exe)
    if pid:
        return get_ports_by_pid(pid)
    return []
# 修改start_service_pywin32函数，添加服务已启动检查
def start_service_pywin32(name, type_name, exe_name):
    config = read_config()
    abspath = config['abspath']
    
    # 构建完整路径：abspath+name+type+exe，并转换为Windows兼容的路径格式
    service_path = os.path.join(abspath, name, type_name, exe_name)
    service_path = os.path.normpath(service_path)
    
    # 检查文件是否存在
    if not os.path.exists(service_path):
        return False, f"服务文件不存在: {service_path}"
    
    # 获取服务显示名称
    service_display_name = get_service_display_name(name, type_name)
    service_name = f"{name}_{type_name}"
    
    # 检查服务是否已经在运行
    try:
        status = win32serviceutil.QueryServiceStatus(service_name)
        if status[1] == win32service.SERVICE_RUNNING:
            with lock:
                service_status[service_name] = "运行中"
            return True, f"服务 {service_display_name} 已经在运行，跳过启动"
    except Exception:
        # 服务不存在或无法获取状态，继续执行后续逻辑
        pass
    
    # 更新状态为启动中
    with lock:
        service_status[service_name] = "启动中"
    
    try:
        # 检查服务是否存在
        try:
            # 尝试获取服务状态
            status = win32serviceutil.QueryServiceStatus(service_name)
            is_installed = True
        except Exception:
            is_installed = False
            
        # 如果服务未安装，先安装服务
        if not is_installed:
            try:
                # 安装服务
                win32serviceutil.InstallService(
                    service_path,  # 服务二进制文件路径
                    service_name,  # 服务名
                    service_display_name,  # 显示名称
                    startType=win32service.SERVICE_DEMAND_START
                )
            except Exception as e:
                return False, f"安装服务失败: {str(e)}"
        
        # 启动服务
        try:
            win32serviceutil.StartService(service_name)
            
            # 等待服务启动
            max_wait_time = 10
            wait_time = 0
            service_running = False
            
            while wait_time < max_wait_time:
                time.sleep(1)
                wait_time += 1
                
                try:
                    status = win32serviceutil.QueryServiceStatus(service_name)
                    if status[1] == win32service.SERVICE_RUNNING:
                        service_running = True
                        break
                except Exception:
                    continue
            
            if service_running:
                with lock:
                    service_status[service_name] = "运行中"
                return True, f"服务 {service_display_name} 启动成功"
            else:
                with lock:
                    service_status[service_name] = "启动失败"
                return False, f"服务 {service_display_name} 启动超时，等待了{max_wait_time}秒未检测到运行状态"
        except Exception as e:
            with lock:
                service_status[service_name] = "启动失败"
            return False, f"启动服务 {service_display_name} 时发生错误: {str(e)}"
    except Exception as e:
        with lock:
            service_status[service_name] = "启动失败"
        return False, f"处理服务 {service_display_name} 时发生错误: {str(e)}"

def start_service(name, type_name, exe_name):
    return start_service_pywin32(name, type_name, exe_name)

def stop_service_pywin32(name, type_name, exe_name):
    """
    通过Windows服务管理停止服务，避免直接杀进程导致的误停
    """
    # 获取服务名称（与服务启动时使用的名称一致）
    service_name = f"{name}_{type_name}"
    service_display_name = get_service_display_name(name, type_name)
    
    try:
        # 检查服务是否存在
        try:
            status = win32serviceutil.QueryServiceStatus(service_name)
            is_installed = True
        except Exception:
            # 服务不存在，直接返回成功
            with lock:
                service_status[service_name] = "未运行"
            return True, f"服务 {service_display_name} 不存在，无需停止"
        
        # 检查服务当前状态
        current_status = status[1]
        
        if current_status == win32service.SERVICE_STOPPED:
            # 服务已经停止
            with lock:
                service_status[service_name] = "未运行"
            return True, f"服务 {service_display_name} 已经停止"
        
        elif current_status == win32service.SERVICE_RUNNING:
            # 服务正在运行，尝试停止
            try:
                # 更新状态为停止中
                with lock:
                    service_status[service_name] = "停止中"
                
                # 停止服务
                win32serviceutil.StopService(service_name)
                
                # 等待服务停止
                max_wait_time = 10
                wait_time = 0
                service_stopped = False
                
                while wait_time < max_wait_time:
                    time.sleep(1)
                    wait_time += 1
                    
                    try:
                        status = win32serviceutil.QueryServiceStatus(service_name)
                        if status[1] == win32service.SERVICE_STOPPED:
                            service_stopped = True
                            break
                    except Exception:
                        continue
                
                if service_stopped:
                    with lock:
                        service_status[service_name] = "未运行"
                    return True, f"服务 {service_display_name} 停止成功"
                else:
                    with lock:
                        service_status[service_name] = "停止失败"
                    return False, f"服务 {service_display_name} 停止超时，等待了{max_wait_time}秒未检测到停止状态"
                    
            except Exception as e:
                with lock:
                    service_status[service_name] = "停止失败"
                return False, f"停止服务 {service_display_name} 时发生错误: {str(e)}"
        
        elif current_status == win32service.SERVICE_STOP_PENDING:
            # 服务正在停止中，等待完成
            max_wait_time = 15
            wait_time = 0
            
            while wait_time < max_wait_time:
                time.sleep(1)
                wait_time += 1
                
                try:
                    status = win32serviceutil.QueryServiceStatus(service_name)
                    if status[1] == win32service.SERVICE_STOPPED:
                        with lock:
                            service_status[service_name] = "未运行"
                        return True, f"服务 {service_display_name} 停止完成"
                except Exception:
                    continue
            
            with lock:
                service_status[service_name] = "停止失败"
            return False, f"服务 {service_display_name} 停止等待超时"
        
        else:
            # 其他状态（如启动中、暂停中等）
            return False, f"服务 {service_display_name} 当前状态不支持停止操作"
            
    except Exception as e:
        return False, f"处理服务 {service_display_name} 时发生错误: {str(e)}"

# 停止服务
def stop_service_quick(name,type_name,exe_name):
    try:
        pid = get_process_id_by_exe(exe_name)
        if pid:
            # 使用psutil终止进程
            process = psutil.Process(pid)
            process.terminate()  # 发送终止信号
            
            # 等待进程终止，最多等待5秒
            try:
                process.wait(timeout=5)
                # 如果提供了name和type_name，更新状态
                if name and type_name:
                    with lock:
                        service_status[f"{name}_{type_name}"] = "未运行"
                return True, f"进程 {pid} 已成功终止"
            except psutil.TimeoutExpired:
                # 如果超时，强制终止
                process.kill()
                # 如果提供了name和type_name，更新状态
                if name and type_name:
                    with lock:
                        service_status[f"{name}_{type_name}"] = "未运行"
                return True, f"进程 {pid} 已强制终止"
        else:
            return False, f"未找到名为 {exe_name} 的进程"
    except Exception as e:
        return False, f"停止服务时发生错误: {str(e)}"

def stop_service(name, type_name, exe_name):
    if type_name == "robot_tool" or type_name == "proxy_game" or type_name =="proxy_room" or type_name == "proxy_assist":
        return stop_service_pywin32(name, type_name, exe_name)

    """
        停止服务的主函数，优先使用Windows服务管理方式
    """
    return stop_service_quick(name, type_name, exe_name)


# 修改deploy_service函数以支持Windows服务安装
def deploy_service(name, type_name, exe_name):
    config = read_config()
    abspath = config['abspath']
    
    # 构建完整路径
    service_path = os.path.join(abspath, name, type_name, exe_name)
    service_path = os.path.normpath(service_path)
    
    # 检查文件是否存在
    if not os.path.exists(service_path):
        return False, f"服务文件不存在: {service_path}"
    
    # 检查name是否存在，如果不存在则创建
    if name not in config['service']:
        config['service'][name] = []
    
    # 检查是否已存在相同type的服务
    # for service in config['service'][name]:
    #     if service['type'] == type_name:
    #         return False, f"服务类型 {type_name} 已存在于 {name} 中"
    
    # 获取服务名称和显示名称
    service_name = f"{name}_{type_name}"
    service_display_name = get_service_display_name(name, type_name)
    
    # 添加新服务到配置（即使服务安装失败，也要添加到配置中）
    # 这样可以确保在前端显示"未部署"状态
    service_exists = False
    for service in config['service'][name]:
        if service['type'] == type_name:
            service_exists = True
            break
    
    if not service_exists:
        config['service'][name].append({'type': type_name, 'exe': exe_name})
        # 保存配置
        save_config(config)
    
    # 尝试使用sc命令安装Windows服务
    windows_service_installed = False
    try:
        # 使用sc create命令创建服务
        # 构造sc命令
        cmd = f'sc create "{service_name}" binPath="{service_path}" DisplayName="{service_display_name}" start= demand'
        
        # 执行命令
        result = os.popen(cmd).read()
        
        # 检查结果是否成功
        if "成功" in result or "SUCCESS" in result.upper():
            windows_service_installed = True
        else:
            # 命令执行失败
            pass
            
    except Exception as e:
        # 执行sc命令失败
        pass
    
    # 构建返回消息
    if windows_service_installed:
        message = f"服务 {service_display_name} 已成功部署到 {name}，并已注册为Windows服务"
    else:
        message = f"服务 {service_display_name} 已成功部署到 {name}（配置已添加，但未注册为Windows服务）"
    
    return True, message

# 添加在API路由部分
def delete_service(name, type_name):
    try:
        config = read_config()
        
        # 检查name是否存在
        if name not in config['service']:
            return False, f"服务组 {name} 不存在"
        
        # 检查type是否存在
        service_to_delete = None
        for i, service in enumerate(config['service'][name]):
            if service['type'] == type_name:
                service_to_delete = i
                exe_name = service['exe']
                break
        
        if service_to_delete is None:
            return False, f"服务类型 {type_name} 在 {name} 中不存在"
        
        # 构建服务名称
        service_display_name = get_service_display_name(name, type_name)
        service_name = f"{name}_{type_name}"
        
        # 停止服务（如果正在运行）
        try:
            stop_service(exe_name, name, type_name)
        except Exception:
            # 即使停止服务失败，也继续执行后续操作
            pass
        
        # 尝试卸载Windows服务（如果已注册）
        try:
            # 检查服务是否存在
            try:
                status = win32serviceutil.QueryServiceStatus(service_name)
                # 如果服务存在，先停止然后删除
                try:
                    stop_service(exe_name, name, type_name)
                except Exception:
                    # 停止服务失败，继续尝试删除
                    pass
                win32serviceutil.RemoveService(service_name)
            except Exception:
                # 服务不存在或无法访问，无需处理
                pass
        except Exception:
            # 导入模块或操作Windows服务失败，无需处理
            pass
        
        # 从service_status中移除服务状态
        if service_name in service_status:
            del service_status[service_name]
        
        return True, f"服务 {service_display_name} 已停止并解除部署，配置信息已保留"
    except Exception as e:
        return False, f"处理服务时发生错误: {str(e)}"
    
# 一键启动所有服务（按script.json中的顺序）
def start_all_services():
    config = read_config()
    script = read_script()
    
    # 如果script.json为空，则按照config.json中的顺序启动
    if not script:
        for name, services in config['service'].items():
            for service in services:
                start_service(name, service['type'], service['exe'])
        return True, "所有服务已按默认顺序启动"
    
    # 按照script.json中的顺序启动
    results = []
    for name in script.get('start_order', []):
        if name in config['service']:
            for service in config['service'][name]:
                success, message = start_service(name, service['type'], service['exe'])
                results.append(message)
        else:
            results.append(f"服务组 {name} 不存在")
    
    return True, "\n".join(results)

# 更新服务文件
def update_service_file(name, type_name, exe_name, new_exe_content, new_pdb_content):
    """
    更新服务文件：停止服务 -> 替换 .exe 和 .pdb 文件 -> 启动服务
    """
    config = read_config()
    abspath = config['abspath']
    
    # 构建 .exe 文件的完整路径
    service_exe_path = os.path.join(abspath, name, type_name, exe_name)
    service_exe_path = os.path.normpath(service_exe_path)
    
    # 构建 .pdb 文件的完整路径
    service_pdb_path = os.path.splitext(service_exe_path)[0] + '.pdb'
    service_pdb_path = os.path.normpath(service_pdb_path)

    if not os.path.exists(service_exe_path):
        return False, f"服务文件不存在，无法更新: {service_exe_path}"

    # 1. 停止服务
    service_display_name = get_service_display_name(name, type_name)
    print(f"正在停止服务以进行更新: {service_display_name}")
    stop_success, stop_msg = stop_service(name, type_name, exe_name)
    
    # 即使停止失败（例如服务本来就没运行），我们也尝试继续，但如果是真正的错误则返回
    if not stop_success and "不存在" not in stop_msg and "已经停止" not in stop_msg and "未找到" not in stop_msg:
        return False, f"停止服务失败，无法更新: {stop_msg}"

    # 等待一会确保进程完全退出
    time.sleep(2)

    # 2. 替换文件
    try:
        # 替换 .exe 文件
        with open(service_exe_path, 'wb') as f:
            f.write(new_exe_content)
        print(f"EXE 文件替换成功: {service_exe_path}")

        # 替换 .pdb 文件
        with open(service_pdb_path, 'wb') as f:
            f.write(new_pdb_content)
        print(f"PDB 文件替换成功: {service_pdb_path}")

    except Exception as e:
        return False, f"替换文件时发生错误: {str(e)}"

    # 3. 启动服务
    print(f"正在重新启动服务: {service_display_name}")
    start_success, start_msg = start_service(name, type_name, exe_name)
    
    if start_success:
        return True, f"服务 {service_display_name} 更新并启动成功"
    else:
        return True, f"服务 {service_display_name} 文件已更新，但启动失败: {start_msg}"

def get_all_service_status():
    config = read_config()
    status_dict = {}
    
    # 获取配置中的基础路径
    base_path = config.get('abspath', '')
    if base_path and not base_path.endswith(('/', '\\')):
        base_path += os.sep
    
    with lock:
        # 遍历config.json中的所有服务配置
        for name, services in config['service'].items():
            for service in services:
                service_id = f"{name}_{service['type']}"
                # 获取服务显示名称
                service_display_name = get_service_display_name(name, service['type'])
                # 修正路径构建：abspath + service下的名称 + type + exe
                # 注意：对于配置文件查找，我们需要exe文件所在的目录，而不是exe文件本身
                service_exe_path = os.path.join(base_path, name, service['type'], service['exe'])
                service_path = os.path.dirname(service_exe_path)  # 获取exe文件所在的目录
                
                # 检查服务是否在service_status中有记录（表示已部署且可能正在运行）
                if service_id in service_status:
                    # 已部署的服务，需要检查真实状态，避免脏状态
                    try:
                        import win32serviceutil
                        import win32service
                        
                        # 获取服务名称
                        service_name = f"{name}_{service['type']}"
                        
                        # 尝试查询服务状态
                        try:
                            status = win32serviceutil.QueryServiceStatus(service_name)
                            # 服务已部署，检查是否正在运行
                            if status[1] == win32service.SERVICE_RUNNING:
                                # 服务正在运行，检查进程是否存在且路径匹配
                                pid = get_process_id_by_exe(service['exe'], service_exe_path)
                                if pid:
                                    # 进程存在，标记为运行中并更新状态
                                    service_status[service_id] = "运行中"
                                    # 获取服务占用的端口
                                    ports = get_ports_by_pid(pid)
                                    port_str = ', '.join(map(str, ports)) if ports else '未监听'
                                    status_dict[service_id] = {
                                        'status': "运行中",
                                        'type': service['type'],
                                        'exe': service['exe'],
                                        'name': name,
                                        'display_name': service_display_name,
                                        'path': service_path,  # 使用目录路径而不是exe文件路径
                                        'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                        'ports': port_str  # 添加端口信息
                                    }
                                else:
                                    # 进程不存在，标记为未运行并更新状态
                                    service_status[service_id] = "未运行"
                                    status_dict[service_id] = {
                                        'status': "未运行",
                                        'type': service['type'],
                                        'exe': service['exe'],
                                        'name': name,
                                        'display_name': service_display_name,
                                        'path': service_path,  # 使用目录路径而不是exe文件路径
                                        'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                        'ports': '未运行'  # 服务未运行，端口状态为未运行
                                    }
                            else:
                                # 服务已部署但未运行
                                service_status[service_id] = "未运行"
                                status_dict[service_id] = {
                                    'status': "未运行",
                                    'type': service['type'],
                                    'exe': service['exe'],
                                        'name': name,
                                        'display_name': service_display_name,
                                        'path': service_path,  # 使用目录路径而不是exe文件路径
                                        'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                        'ports': '未运行'  # 服务未运行，端口状态为未运行
                                    }
                        except Exception:
                            # 查询服务状态失败，说明服务未部署
                            status_dict[service_id] = {
                                'status': "未部署",
                                'type': service['type'],
                                'exe': service['exe'],
                                'name': name,
                                'display_name': service_display_name,
                                'path': service_path,  # 使用目录路径而不是exe文件路径
                                'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                'ports': '未部署'  # 服务未部署，端口状态为未部署
                            }
                    except ImportError:
                        # pywin32不可用，回退到原来的检查方式
                        # 检查进程是否存在以确定是未运行还是未部署
                        pid = get_process_id_by_exe(service['exe'], service_exe_path)
                        if pid:
                            # 进程存在但service_status中无记录，标记为运行中并更新状态
                            service_status[service_id] = "运行中"
                            # 获取服务占用的端口
                            ports = get_ports_by_pid(pid)
                            port_str = ', '.join(map(str, ports)) if ports else '未监听'
                            status_dict[service_id] = {
                                'status': "运行中",
                                'type': service['type'],
                                'exe': service['exe'],
                                'name': name,
                                'display_name': service_display_name,
                                'path': service_path,  # 使用目录路径而不是exe文件路径
                                'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                'ports': port_str  # 添加端口信息
                            }
                        else:
                            # 进程不存在且service_status中无记录，标记为未部署
                            status_dict[service_id] = {
                                'status': "未部署",
                                'type': service['type'],
                                'exe': service['exe'],
                                'name': name,
                                'display_name': service_display_name,
                                'path': service_path,  # 使用目录路径而不是exe文件路径
                                'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                'ports': '未部署'  # 服务未部署，端口状态为未部署
                            }
                else:
                    # 服务在config.json中存在但不在service_status中，需要进一步检查
                    try:
                        import win32serviceutil
                        import win32service
                        
                        # 获取服务名称
                        service_name = f"{name}_{service['type']}"
                        
                        # 尝试查询服务状态
                        try:
                            # 如果能查询到服务状态，说明服务已部署
                            status = win32serviceutil.QueryServiceStatus(service_name)
                            # 服务已部署，检查是否正在运行
                            if status[1] == win32service.SERVICE_RUNNING:
                                # 服务正在运行，检查进程是否存在且路径匹配
                                pid = get_process_id_by_exe(service['exe'], service_exe_path)
                                if pid:
                                    # 进程存在，标记为运行中并更新状态
                                    service_status[service_id] = "运行中"
                                    # 获取服务占用的端口
                                    ports = get_ports_by_pid(pid)
                                    port_str = ', '.join(map(str, ports)) if ports else '未监听'
                                    status_dict[service_id] = {
                                        'status': "运行中",
                                        'type': service['type'],
                                        'exe': service['exe'],
                                        'name': name,
                                        'display_name': service_display_name,
                                        'path': service_path,  # 使用目录路径而不是exe文件路径
                                        'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                        'ports': port_str  # 添加端口信息
                                    }
                                else:
                                    # 进程不存在，标记为未运行并更新状态
                                    service_status[service_id] = "未运行"
                                    status_dict[service_id] = {
                                        'status': "未运行",
                                        'type': service['type'],
                                        'exe': service['exe'],
                                        'name': name,
                                        'display_name': service_display_name,
                                        'path': service_path,  # 使用目录路径而不是exe文件路径
                                        'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                        'ports': '未运行'  # 服务未运行，端口状态为未运行
                                    }
                            else:
                                # 服务已部署但未运行
                                service_status[service_id] = "未运行"
                                status_dict[service_id] = {
                                    'status': "未运行",
                                    'type': service['type'],
                                    'exe': service['exe'],
                                    'name': name,
                                    'display_name': service_display_name,
                                    'path': service_path,  # 使用目录路径而不是exe文件路径
                                    'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                    'ports': '未运行'  # 服务未运行，端口状态为未运行
                                }
                        except Exception:
                            # 查询服务状态失败，说明服务未部署
                            status_dict[service_id] = {
                                'status': "未部署",
                                'type': service['type'],
                                'exe': service['exe'],
                                'name': name,
                                'display_name': service_display_name,
                                'path': service_path,  # 使用目录路径而不是exe文件路径
                                'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                'ports': '未部署'  # 服务未部署，端口状态为未部署
                            }
                    except ImportError:
                        # pywin32 不可用，回退到原来的检查方式
                        # 检查进程是否存在以确定是未运行还是未部署
                        pid = get_process_id_by_exe(service['exe'], service_exe_path)
                        if pid:
                            # 进程存在但service_status中无记录，标记为运行中并更新状态
                            service_status[service_id] = "运行中"
                            # 获取服务占用的端口
                            ports = get_ports_by_pid(pid)
                            port_str = ', '.join(map(str, ports)) if ports else '未监听'
                            status_dict[service_id] = {
                                'status': "运行中",
                                'type': service['type'],
                                'exe': service['exe'],
                                'name': name,
                                'display_name': service_display_name,
                                'path': service_path,  # 使用目录路径而不是exe文件路径
                                'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                'ports': port_str  # 添加端口信息
                            }
                        else:
                            # 进程不存在且service_status中无记录，标记为未部署
                            status_dict[service_id] = {
                                'status': "未部署",
                                'type': service['type'],
                                'exe': service['exe'],
                                'name': name,
                                'display_name': service_display_name,
                                'path': service_path,  # 使用目录路径而不是exe文件路径
                                'exe_path': service_exe_path,  # 保留exe文件的完整路径
                                'ports': '未部署'  # 服务未部署，端口状态为未部署
                            }
    
    return status_dict

import subprocess

def get_svn_status():
    """
    检查SVN仓库状态，判断是否为最新版本。
    """
    config = read_config()
    svn_path = config.get('svnPath')

    if not svn_path:
        return False, "config.json 中未配置 svnPath"

    try:
        # 检查工作副本状态
        # 使用 --non-interactive 防止需要凭据时挂起
        # 注意: svnPath 是仓库 URL(非本地路径), 不能当 cwd; 工作副本根 = 进程 cwd (launcher 从 infoServer 根启动)
        result = subprocess.run(['svn', 'status', '-u', '--non-interactive'],
                                capture_output=True, text=True, check=True, encoding='gbk',
                                cwd=os.getcwd())
        output = result.stdout.strip()
        
        # 将输出按行分割，并过滤掉 "Status against revision:" 开头的行
        status_lines = [line for line in output.splitlines() if not line.startswith('Status against revision:')]
        
        needs_update = False
        for line in status_lines:
            # 远程 out-of-date 标记 `*` 在 svn status -u 的第 8 列(index 8, 前 7 列是本地状态;
            # 本地干净时 * 是整行唯一标记, 本地 M/? 不影响其位置)。`!` = 本地 missing, update 会拉回, 也需同步。
            if line.startswith('!') or (len(line) >= 9 and line[8] == '*'):
                needs_update = True
                break
        
        if needs_update:
            return False, "工作副本有未同步的更改"
        else:
            return True, "已经是最新版本"

    except subprocess.CalledProcessError as e:
        # 如果 svn status 返回非零，可能表示工作副本有问题或凭据问题
        error_message = e.stderr.strip()
        if "not a working copy" in error_message.lower():
            return False, f"SVN路径 '{svn_path}' 不是一个工作副本。"
        elif "authentication required" in error_message.lower() or "authorization failed" in error_message.lower():
            return False, "SVN认证失败，请检查凭据。"
        return False, f"执行SVN状态检查失败: {error_message}"
    except FileNotFoundError:
        return False, "未找到SVN客户端，请确保已安装并配置环境变量"
    except Exception as e:
        return False, f"检查SVN状态时发生未知错误: {str(e)}"

def update_svn():
    """
    执行SVN更新操作。
    """
    config = read_config()
    svn_path = config.get('svnPath')

    if not svn_path:
        return False, "config.json 中未配置 svnPath"

    try:
        # 执行 svn update 命令
        result = subprocess.run(['svn', 'update', '--non-interactive'], capture_output=True, text=True, encoding='gbk')
        
        if result.returncode == 0:
            # 更新成功或已经是最新版本
            output = result.stdout.strip()
            if "Updated to revision" in output:
                return True, f"SVN更新成功: {output}"
            elif "At revision" in output:
                return True, f"SVN已经是最新版本: {output}"
            else:
                # 其他成功的输出，例如没有文件更新
                return True, f"SVN更新完成: {output}"
        else:
            # 非零返回码表示错误
            error_message = result.stderr.strip()
            if "not a working copy" in error_message.lower():
                return False, f"SVN路径 '{svn_path}' 不是一个工作副本。"
            elif "authentication required" in error_message.lower() or "authorization failed" in error_message.lower():
                return False, "SVN认证失败，请检查凭据。"
            return False, f"执行SVN更新失败: {error_message}"

    except FileNotFoundError:
        return False, "未找到SVN客户端，请确保已安装并配置环境变量"
    except Exception as e:
        return False, f"执行SVN更新时发生未知错误: {str(e)}"

def read_file_content(file_path, encoding='utf-8'):
    """
    读取文件内容，尝试使用指定编码，如果失败则尝试其他常见编码，
    最后回退到 latin-1 (errors='ignore') 以确保不会出错。
    返回内容和实际使用的编码。
    """
    with open(file_path, 'rb') as f:
        raw_data = f.read()

    # 尝试用户指定的编码
    try:
        content = raw_data.decode(encoding, errors='replace')
        return content, encoding
    except (UnicodeDecodeError, LookupError):
        pass # 继续尝试其他编码

    # 尝试其他常见编码
    common_encodings = ['utf-8', 'gbk', 'utf-16-le', 'utf-16-be']
    # 移除已尝试的编码，避免重复
    if encoding in common_encodings:
        common_encodings.remove(encoding)

    for enc in common_encodings:
        try:
            content = raw_data.decode(enc, errors='replace')
            return content, enc
        except (UnicodeDecodeError, LookupError):
            pass # 继续尝试下一个编码

    # 最后回退到 latin-1，并忽略所有错误，确保不会抛出异常
    final_encoding = 'latin-1'
    content = raw_data.decode(final_encoding, errors='ignore')
    return content, final_encoding

def save_file_content(file_path, content, encoding='utf-8'):
    """
    保存文件内容，使用指定编码，并处理备份和错误恢复。
    """
    import shutil
    
    # 备份原文件
    backup_path = file_path + '.backup'
    if os.path.exists(file_path):
        try:
            shutil.copy2(file_path, backup_path)
        except Exception as e:
            print(f"备份文件 '{file_path}' 失败: {str(e)}")
            # 备份失败不阻止保存，但记录错误

    try:
        # 尝试使用指定编码写入文件
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)
        
        # 如果成功，删除备份文件
        if os.path.exists(backup_path):
            os.remove(backup_path)
            
    except UnicodeEncodeError:
        # 如果指定编码写入失败，直接抛出异常
        raise Exception(f"内容无法使用指定的编码 '{encoding}' 进行编码。")

    except Exception as e:
        # 如果保存失败，尝试恢复备份
        print(f"保存文件 '{file_path}' 失败: {str(e)}")
        if os.path.exists(backup_path):
            try:
                shutil.move(backup_path, file_path)
                print(f"已从备份恢复文件 '{file_path}'。")
            except Exception as restore_e:
                print(f"恢复备份文件 '{file_path}' 失败: {str(restore_e)}")
        raise Exception(f"保存文件失败: {str(e)}")



