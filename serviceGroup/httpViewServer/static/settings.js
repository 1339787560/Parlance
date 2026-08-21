// 共享设置面板组件
(function() {
    // 创建设置面板的HTML结构
    function createSettingsHTML() {
        const settingsHTML = `
            <!-- 聚合搜索按钮 -->
            <button id="aggSearchButton" class="agg-search-button" title="聚合搜索 (Ctrl+Shift+P)">🔍</button>

            <!-- 设置按钮 - 改为齿轮图标 -->
            <button id="settingsButton" class="settings-button">⚙️</button>
            
            <!-- 设置弹窗 -->
            <div id="settingsModal" class="modal-overlay">
                <div class="modal-content">
                    <div class="modal-header">
                        <h2>设置</h2>
                        <button id="closeModalButton" class="close-button">×</button>
                    </div>
                    <div class="modal-body">
                        <!-- 服务端间隔提供图片设置 -->
                        <div class="interval-setting">
                            <label class="checkbox-group">
                                <input type="checkbox" id="enableImageInterval"> 服务端间隔提供图片
                            </label>
                            <div class="interval-input-group" id="intervalInputContainer" style="display: none;">
                                <span>间隔数量 (n):</span>
                                <input type="number" id="imageInterval" min="0" value="0" oninput="validateIntervalInput(this)">
                                <span>张</span>
                            </div>
                            <div class="current-value">
                                当前设置: <span id="currentIntervalValue">0</span> 张
                            </div>
                        </div>
                        
                        <!-- 漫画模式设置 -->
                        <div class="comic-mode-setting">
                            <label class="checkbox-group">
                                <input type="checkbox" id="enableComicMode"> 漫画模式（按文件夹名称中第一个数字排序）
                            </label>
                            <div class="comic-input-group" id="comicInputContainer" style="display: none; margin-left: 32px; margin-top: 10px;">
                                <span>最大拼接话数:</span>
                                <input type="number" id="maxComicEpisodes" min="1" value="100" oninput="validateMaxComicEpisodes(this)">
                                <span>话</span>
                            </div>
                        </div>
                        
                        <!-- 图片加载起始位置设置（固定位置和百分比只能二选一） -->
                        <div class="position-settings-group" style="margin-top: 20px;">
                            <div style="margin-bottom: 10px;">图片加载起始位置设置：</div>
                            
                            <!-- 固定位置起始加载设置 -->
                            <div class="position-setting">
                                <label class="checkbox-group">
                                    <input type="radio" name="startPositionType" id="enableFixedPosition"> 从固定位置加载
                                </label>
                                <div class="position-input-group" id="fixedPositionContainer" style="display: none; margin-left: 32px;">
                                    <div style="margin-bottom: 10px;">
                                        <span>起始位置 (x):</span>
                                        <input type="number" id="startPosition" min="0" value="0" oninput="validatePositionInput(this)">
                                        <span>张</span>
                                    </div>
                                    <div>
                                        <span>加载数量 (n):</span>
                                        <input type="number" id="loadCount" min="1" value="10" oninput="validateCountInput(this)">
                                        <span>张</span>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- 百分比位置起始加载设置 -->
                            <div class="position-setting">
                                <label class="checkbox-group">
                                    <input type="radio" name="startPositionType" id="enablePercentagePosition"> 从百分比位置加载
                                </label>
                                <div class="position-input-group" id="percentageContainer" style="display: none; margin-left: 32px;">
                                    <div style="margin-bottom: 10px;">
                                        <span>起始百分比 (%):</span>
                                        <input type="number" id="startPercentage" min="0" max="100" value="0" oninput="validatePercentageInput(this)">
                                        <span>%</span>
                                    </div>
                                    <div>
                                        <span>加载数量 (n):</span>
                                        <input type="number" id="percentageLoadCount" min="1" value="10" oninput="validateCountInput(this)">
                                        <span>张</span>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- 默认选项：加载全部图片 -->
                            <div class="position-setting">
                                <label class="checkbox-group">
                                    <input type="radio" name="startPositionType" id="disablePositionSetting" checked> 加载全部图片
                                </label>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button onclick="closeModal()" style="padding: 10px 20px; background: #f5f5f5; border: none; border-radius: 5px; cursor: pointer;">取消</button>
                        <button onclick="saveSettings()" style="padding: 10px 20px; background: #2196F3; color: white; border: none; border-radius: 5px; cursor: pointer;">保存设置</button>
                    </div>
                </div>
            </div>

            <!-- 聚合搜索弹窗 -->
            <div id="aggSearchModal" class="modal-overlay">
                <div class="modal-content" style="max-width: 520px;">
                    <div class="modal-header">
                        <h2>🔍 聚合搜索</h2>
                        <button id="aggSearchCloseBtn" class="close-button">×</button>
                    </div>
                    <div class="modal-body">
                        <div style="margin-bottom: 12px; color: #666; font-size: 13px; line-height: 1.6;">
                            以<b>当前目录</b>作为根目录，递归搜索视频文件名。<br>
                            支持 <b>|</b>（满足任一）与 <b>&</b>（同时满足），例如 <code>猫|狗</code>、<code>猫&狗</code>、<code>猫|狗&鱼</code>。
                        </div>
                        <input type="text" id="aggSearchInput" placeholder="输入关键词，用 | 或 & 组合"
                            style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; box-sizing: border-box;">
                        <div style="margin-top: 12px; display: flex; gap: 24px;">
                            <label class="checkbox-group"><input type="checkbox" id="aggCaseSensitive"> 区分大小写</label>
                            <label class="checkbox-group"><input type="checkbox" id="aggWholeWord"> 全字匹配</label>
                        </div>
                        <div id="aggSearchStatus" style="margin-top: 12px; font-size: 13px; color: #666; min-height: 18px;"></div>
                    </div>
                    <div class="modal-footer">
                        <button id="aggSearchCancelBtn" style="padding: 10px 20px; background: #f5f5f5; border: none; border-radius: 5px; cursor: pointer;">取消</button>
                        <button id="aggSearchSubmitBtn" style="padding: 10px 20px; background: #2196F3; color: white; border: none; border-radius: 5px; cursor: pointer;">搜索并创建</button>
                    </div>
                </div>
            </div>
        `;
        return settingsHTML;
    }
    
    // 创建设置面板的CSS样式
    function createSettingsCSS() {
        const settingsCSS = `
            /* 设置按钮样式 */
            .settings-button {
                position: fixed;
                bottom: 20px;
                right: 20px;
                width: 50px;
                height: 50px;
                background: rgba(255, 255, 255, 0.9);
                border: none;
                border-radius: 50%;
                font-size: 24px;
                cursor: pointer;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
                z-index: 9998;
                transition: background 0.3s;
            }
            
            .settings-button:hover {
                background: rgba(255, 255, 255, 1);
            }

            /* 聚合搜索按钮样式 */
            .agg-search-button {
                position: fixed;
                bottom: 20px;
                right: 80px;
                width: 50px;
                height: 50px;
                background: rgba(33, 150, 243, 0.9);
                color: white;
                border: none;
                border-radius: 50%;
                font-size: 22px;
                cursor: pointer;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
                z-index: 9998;
                transition: background 0.3s;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .agg-search-button:hover {
                background: rgba(33, 150, 243, 1);
            }
            
            /* 弹窗样式 */
            .modal-overlay {
                display: none;
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.5);
                justify-content: center;
                align-items: center;
                z-index: 9999;
            }
            
            .modal-overlay.active {
                display: flex;
            }
            
            .modal-content {
                background: white;
                border-radius: 8px;
                width: 90%;
                max-width: 500px;
                max-height: 90vh;
                overflow-y: auto;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
            }
            
            .modal-header {
                padding: 20px;
                border-bottom: 1px solid #eee;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            
            .modal-header h2 {
                margin: 0;
                font-size: 18px;
            }
            
            .close-button {
                background: none;
                border: none;
                font-size: 24px;
                cursor: pointer;
                color: #999;
                padding: 0;
                width: 30px;
                height: 30px;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            
            .close-button:hover {
                color: #333;
            }
            
            .modal-body {
                padding: 20px;
            }
            
            .modal-footer {
                padding: 15px 20px;
                border-top: 1px solid #eee;
                display: flex;
                justify-content: flex-end;
                gap: 10px;
            }
            
            /* 设置项样式 */
            .interval-setting {
                margin-bottom: 20px;
            }
            
            .comic-mode-setting {
                margin-bottom: 20px;
            }
            
            .checkbox-group {
                display: flex;
                align-items: center;
                gap: 8px;
            }
            
            .interval-input-group {
                display: flex;
                align-items: center;
                gap: 10px;
                margin-left: 32px;
                margin-bottom: 10px;
            }
            
            .comic-input-group {
                display: flex;
                align-items: center;
                gap: 10px;
                margin-left: 32px;
                margin-bottom: 10px;
            }
            
            .interval-input-group input {
                width: 80px;
                padding: 5px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            
            .comic-input-group input {
                width: 80px;
                padding: 5px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            
            .current-value {
                margin-left: 32px;
                font-size: 14px;
                color: #666;
            }
            
            .position-settings-group {
                margin-top: 20px;
            }
            
            .position-setting {
                margin-bottom: 15px;
            }
            
            .position-input-group {
                display: flex;
                align-items: center;
                gap: 10px;
                margin-bottom: 10px;
                flex-wrap: wrap;
            }
            
            .position-input-group input {
                width: 80px;
                padding: 5px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
        `;
        return settingsCSS;
    }
    
    // 初始化设置面板
    function initSettingsPanel() {
        // 添加CSS样式到head
        const styleElement = document.createElement('style');
        styleElement.textContent = createSettingsCSS();
        document.head.appendChild(styleElement);
        
        // 添加HTML结构到body
        const settingsContainer = document.createElement('div');
        settingsContainer.id = 'settings-panel-container';
        settingsContainer.innerHTML = createSettingsHTML();
        document.body.appendChild(settingsContainer);
        
        // 全局变量定义
        window.settingsButton = document.getElementById('settingsButton');
        window.settingsModal = document.getElementById('settingsModal');
        window.closeModalButton = document.getElementById('closeModalButton');
        window.enableImageInterval = document.getElementById('enableImageInterval');
        window.intervalInputContainer = document.getElementById('intervalInputContainer');
        window.imageInterval = document.getElementById('imageInterval');
        window.currentIntervalValue = document.getElementById('currentIntervalValue');
        window.enableFixedPosition = document.getElementById('enableFixedPosition');
        window.fixedPositionContainer = document.getElementById('fixedPositionContainer');
        window.startPosition = document.getElementById('startPosition');
        window.loadCount = document.getElementById('loadCount');
        window.enablePercentagePosition = document.getElementById('enablePercentagePosition');
        window.percentageContainer = document.getElementById('percentageContainer');
        window.startPercentage = document.getElementById('startPercentage');
        window.percentageLoadCount = document.getElementById('percentageLoadCount');
        window.disablePositionSetting = document.getElementById('disablePositionSetting');
        window.enableComicMode = document.getElementById('enableComicMode'); // 新增漫画模式
        window.comicInputContainer = document.getElementById('comicInputContainer'); // 新增漫画模式输入容器
        window.maxComicEpisodes = document.getElementById('maxComicEpisodes'); // 新增最大拼接话数
        
        // 添加事件监听器
        settingsButton.addEventListener('click', openModal);
        closeModalButton.addEventListener('click', closeModal);
        enableImageInterval.addEventListener('change', function() {
            intervalInputContainer.style.display = this.checked ? 'flex' : 'none';
        });
        
        // 新增漫画模式事件监听 - 实时响应切换
        enableComicMode.addEventListener('change', function() {
            comicInputContainer.style.display = this.checked ? 'flex' : 'none';
            
            // 保存漫画模式状态到localStorage
            localStorage.setItem('enableComicMode', this.checked);
            
            // 获取当前URL并更新comic_mode参数
            const url = new URL(window.location.href);
            if (this.checked) {
                url.searchParams.set('comic_mode', 'true');
            } else {
                url.searchParams.delete('comic_mode');
            }
            
            // 刷新页面，这将使用更新后的URL参数重新加载页面
            window.location.href = url.toString();
        });
        
        enableFixedPosition.addEventListener('change', function() {
            fixedPositionContainer.style.display = this.checked ? 'block' : 'none';
            if (this.checked) {
                percentageContainer.style.display = 'none';
            }
        });
        
        enablePercentagePosition.addEventListener('change', function() {
            percentageContainer.style.display = this.checked ? 'block' : 'none';
            if (this.checked) {
                fixedPositionContainer.style.display = 'none';
            }
        });
        
        disablePositionSetting.addEventListener('change', function() {
            if (this.checked) {
                fixedPositionContainer.style.display = 'none';
                percentageContainer.style.display = 'none';
            }
        });
        
        // 点击弹窗外部关闭弹窗
        settingsModal.addEventListener('click', function(e) {
            if (e.target === settingsModal) {
                closeModal();
            }
        });

        // 聚合搜索按钮与弹窗
        window.aggSearchButton = document.getElementById('aggSearchButton');
        window.aggSearchModal = document.getElementById('aggSearchModal');
        window.aggSearchInput = document.getElementById('aggSearchInput');
        window.aggCaseSensitive = document.getElementById('aggCaseSensitive');
        window.aggWholeWord = document.getElementById('aggWholeWord');
        window.aggSearchStatus = document.getElementById('aggSearchStatus');

        if (aggSearchButton) {
            aggSearchButton.addEventListener('click', openAggSearch);
            document.getElementById('aggSearchCloseBtn').addEventListener('click', closeAggSearch);
            document.getElementById('aggSearchCancelBtn').addEventListener('click', closeAggSearch);
            document.getElementById('aggSearchSubmitBtn').addEventListener('click', performAggSearch);
            aggSearchModal.addEventListener('click', function(e) {
                if (e.target === aggSearchModal) closeAggSearch();
            });
            aggSearchInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') performAggSearch();
            });
            // 快捷键 Ctrl+Shift+P 打开聚合搜索
            document.addEventListener('keydown', function(e) {
                if (e.ctrlKey && e.shiftKey && e.code === 'KeyP') {
                    e.preventDefault();
                    openAggSearch();
                }
            });
        }

        // 加载设置
        loadSettings();
    }
    
    // 打开弹窗
    window.openModal = function() {
        settingsModal.classList.add('active');
        document.body.style.overflow = 'hidden'; // 防止背景滚动
    }

    // ===== 聚合搜索 =====
    // 获取当前页面对应的目录（作为搜索根目录）
    window.getCurrentBrowsePath = function() {
        const p = window.location.pathname;
        if (p.startsWith('/browse/')) return decodeURIComponent(p.slice('/browse/'.length));
        if (p.startsWith('/gallery/')) return decodeURIComponent(p.slice('/gallery/'.length));
        return ''; // 根目录
    }

    window.openAggSearch = function() {
        aggSearchModal.classList.add('active');
        document.body.style.overflow = 'hidden';
        aggSearchStatus.textContent = '';
        aggSearchStatus.style.color = '#666';
        setTimeout(() => aggSearchInput.focus(), 50);
    }

    window.closeAggSearch = function() {
        aggSearchModal.classList.remove('active');
        document.body.style.overflow = '';
    }

    window.performAggSearch = function() {
        const q = aggSearchInput.value.trim();
        if (!q) {
            aggSearchStatus.style.color = '#f44336';
            aggSearchStatus.textContent = '请输入搜索关键词';
            return;
        }
        const root = getCurrentBrowsePath();
        const params = new URLSearchParams();
        params.append('root', root);
        params.append('q', q);
        params.append('case_sensitive', aggCaseSensitive.checked);
        params.append('whole_word', aggWholeWord.checked);

        const submitBtn = document.getElementById('aggSearchSubmitBtn');
        aggSearchStatus.style.color = '#666';
        aggSearchStatus.textContent = '搜索中...';
        submitBtn.disabled = true;

        fetch(`/aggsearch/create?${params.toString()}`)
            .then(r => {
                if (!r.ok) {
                    return r.text().then(() => Promise.reject(new Error(`HTTP ${r.status}`)));
                }
                const ct = r.headers.get('content-type') || '';
                if (!ct.includes('application/json')) {
                    return r.text().then(() => Promise.reject(new Error('服务器返回非JSON响应（可能未重启加载新路由）')));
                }
                return r.json();
            })
            .then(data => {
                submitBtn.disabled = false;
                if (!data.success) {
                    aggSearchStatus.style.color = '#f44336';
                    aggSearchStatus.textContent = data.error || '搜索失败';
                    return;
                }
                if (data.count === 0) {
                    aggSearchStatus.style.color = '#FF9800';
                    aggSearchStatus.textContent = '未找到匹配的视频，未创建目录';
                    return;
                }
                aggSearchStatus.style.color = '#4CAF50';
                aggSearchStatus.textContent = `找到 ${data.count} 个结果，已创建聚合搜索目录`;
                setTimeout(() => {
                    closeAggSearch();
                    window.location.reload();
                }, 800);
            })
            .catch(err => {
                submitBtn.disabled = false;
                aggSearchStatus.style.color = '#f44336';
                aggSearchStatus.textContent = '搜索失败: ' + (err.message || err);
            });
    }
    
    // 关闭弹窗
    window.closeModal = function() {
        settingsModal.classList.remove('active');
        document.body.style.overflow = ''; // 恢复背景滚动
    }
    
    // 保存设置 - 可以被重写以支持不同页面的特定行为
    window.saveSettings = function() {
        // 保存间隔设置
        localStorage.setItem('enableImageInterval', enableImageInterval.checked);
        localStorage.setItem('imageInterval', imageInterval.value);
        
        // 保存漫画模式设置
        localStorage.setItem('enableComicMode', enableComicMode.checked); // 新增漫画模式保存
        localStorage.setItem('maxComicEpisodes', maxComicEpisodes.value); // 新增最大拼接话数保存
        
        // 保存位置类型设置
        localStorage.setItem('positionType', 
            enableFixedPosition.checked ? 'fixed' : 
            enablePercentagePosition.checked ? 'percentage' : 'none');
        
        // 保存固定位置设置
        localStorage.setItem('startPosition', startPosition.value);
        localStorage.setItem('loadCount', loadCount.value);
        
        // 保存百分比位置设置
        localStorage.setItem('startPercentage', startPercentage.value);
        localStorage.setItem('percentageLoadCount', percentageLoadCount.value);
        
        // 更新当前显示值
        currentIntervalValue.textContent = imageInterval.value;
        
        // 关闭弹窗
        closeModal();
    }
    
    // 加载设置
    window.loadSettings = function() {
        // 加载间隔设置
        enableImageInterval.checked = localStorage.getItem('enableImageInterval') === 'true';
        imageInterval.value = localStorage.getItem('imageInterval') || '0';
        currentIntervalValue.textContent = imageInterval.value;
        intervalInputContainer.style.display = enableImageInterval.checked ? 'flex' : 'none';
        
        // 加载漫画模式设置
        const comicModeEnabled = localStorage.getItem('enableComicMode') === 'true';
        enableComicMode.checked = comicModeEnabled; // 新增漫画模式加载
        maxComicEpisodes.value = localStorage.getItem('maxComicEpisodes') || '100'; // 新增最大拼接话数加载
        comicInputContainer.style.display = enableComicMode.checked ? 'flex' : 'none';
        
        // 保存当前漫画模式状态，用于比较变化
        window.previousComicMode = comicModeEnabled;
        
        // 加载位置类型设置
        const positionType = localStorage.getItem('positionType') || 'none';
        enableFixedPosition.checked = positionType === 'fixed';
        enablePercentagePosition.checked = positionType === 'percentage';
        disablePositionSetting.checked = positionType === 'none';
        
        // 保存固定位置设置
        startPosition.value = localStorage.getItem('startPosition') || '0';
        loadCount.value = localStorage.getItem('loadCount') || '10';
        fixedPositionContainer.style.display = enableFixedPosition.checked ? 'block' : 'none';
        
        // 保存百分比位置设置
        startPercentage.value = localStorage.getItem('startPercentage') || '0';
        percentageLoadCount.value = localStorage.getItem('percentageLoadCount') || '10';
        percentageContainer.style.display = enablePercentagePosition.checked ? 'block' : 'none';
    }
    
    // 验证输入是否为非负整数
    window.validateIntervalInput = function(input) {
        let value = parseInt(input.value);
        if (isNaN(value) || value < 0) {
            value = 0;
        }
        input.value = value;
    }
    
    // 验证位置输入
    window.validatePositionInput = function(input) {
        let value = parseInt(input.value);
        if (isNaN(value) || value < 0) {
            value = 0;
        }
        input.value = value;
    }
    
    // 验证数量输入
    window.validateCountInput = function(input) {
        let value = parseInt(input.value);
        if (isNaN(value) || value < 1) {
            value = 1;
        }
        input.value = value;
    }
    
    // 验证百分比输入
    window.validatePercentageInput = function(input) {
        let value = parseInt(input.value);
        if (isNaN(value) || value < 0) {
            value = 0;
        } else if (value > 100) {
            value = 100;
        }
        input.value = value;
    }
    
    // 验证最大拼接话数输入
    window.validateMaxComicEpisodes = function(input) {
        let value = parseInt(input.value);
        if (isNaN(value) || value < 1) {
            value = 1;
        }
        input.value = value;
    }
    
    // 当DOM加载完成后初始化设置面板
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initSettingsPanel);
    } else {
        initSettingsPanel();
    }
})();