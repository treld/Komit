// ========== Состояние ==========
let allPlugins = [];
let currentTab = 'all';
let configPluginId = null;
let refreshInterval = null;

// ========== Инициализация ==========
document.addEventListener('DOMContentLoaded', () => {
    loadPlugins();

    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
            this.classList.add('active');
            currentTab = this.dataset.tab;
            updatePageTitle();
            filterPlugins();
        });
    });

    const searchInput = document.getElementById('searchInput');
    searchInput.addEventListener('input', function() {
        document.getElementById('searchClear').style.display = this.value ? 'block' : 'none';
        filterPlugins();
    });

    document.querySelector('.modal-backdrop')?.addEventListener('click', closeConfig);

    // Автообновление
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(() => {
        if (!document.hidden) loadPlugins();
    }, 30000);
});

// ========== API ==========
function loadPlugins() {
    showLoading();

    fetch('/api/plugins')
        .then(res => {
            if (!res.ok) throw new Error('HTTP ' + res.status);
            return res.json();
        })
        .then(plugins => {
            allPlugins = plugins;
            updateBadges();
            filterPlugins();
        })
        .catch(error => {
            showToast('❌ Ошибка загрузки: ' + error.message, 'error');
            document.getElementById('pluginsContainer').innerHTML = `
                <div class="empty-state">
                    <span class="empty-icon">🔌</span>
                    <h3>Не удалось загрузить плагины</h3>
                    <p>${error.message}</p>
                    <button onclick="loadPlugins()" class="btn btn-primary" style="margin-top:16px;">
                        <i class="fas fa-redo"></i> Попробовать снова
                    </button>
                </div>
            `;
        });
}

function updateBadges() {
    const installed = allPlugins.filter(p => p.is_installed);
    const updates = allPlugins.filter(p => p.has_update);
    const running = allPlugins.filter(p => p.is_running);

    document.getElementById('total-count').textContent = allPlugins.length;
    document.getElementById('installed-count').textContent = installed.length;
    document.getElementById('updates-count').textContent = updates.length;
    document.getElementById('running-count').textContent = running.length;

    const updatesBadge = document.querySelector('.nav-link[data-tab="updates"] .nav-badge');
    if (updates.length > 0) {
        updatesBadge.classList.add('updates-available');
    } else {
        updatesBadge.classList.remove('updates-available');
    }
}

function updatePageTitle() {
    const titles = {
        'all': 'Все плагины',
        'installed': 'Установленные',
        'updates': 'Обновления',
        'running': 'Запущенные'
    };
    const icons = {
        'all': 'fa-th-large',
        'installed': 'fa-check-circle',
        'updates': 'fa-sync-alt',
        'running': 'fa-play-circle'
    };
    document.querySelector('.page-title').innerHTML =
        `<i class="fas ${icons[currentTab] || icons.all}"></i> ${titles[currentTab] || 'Все плагины'}`;
}

function filterPlugins() {
    const search = document.getElementById('searchInput').value.toLowerCase().trim();
    let filtered = allPlugins;

    if (currentTab === 'installed') {
        filtered = filtered.filter(p => p.is_installed);
    } else if (currentTab === 'updates') {
        filtered = filtered.filter(p => p.has_update);
    } else if (currentTab === 'running') {
        filtered = filtered.filter(p => p.is_running);
    }

    if (search) {
        filtered = filtered.filter(p =>
            p.name.toLowerCase().includes(search) ||
            p.description.toLowerCase().includes(search) ||
            p.author.toLowerCase().includes(search)
        );
    }

    renderPlugins(filtered);
}

function clearSearch() {
    document.getElementById('searchInput').value = '';
    document.getElementById('searchClear').style.display = 'none';
    filterPlugins();
}

// ========== Рендеринг ==========
function renderPlugins(plugins) {
    const container = document.getElementById('pluginsContainer');

    if (!plugins || plugins.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">🔍</span>
                <h3>Ничего не найдено</h3>
                <p>Попробуйте изменить параметры поиска</p>
            </div>
        `;
        return;
    }

    plugins.sort((a, b) => {
        if (a.is_running && !b.is_running) return -1;
        if (!a.is_running && b.is_running) return 1;
        if (a.is_installed && !b.is_installed) return -1;
        if (!a.is_installed && b.is_installed) return 1;
        return a.name.localeCompare(b.name);
    });

    container.innerHTML = plugins.map(plugin => renderPluginCard(plugin)).join('');
}

function renderPluginCard(plugin) {
    // Иконка с обработкой ошибок
    let iconHtml = '';
    if (plugin.icon_url) {
        iconHtml = `<img src="${plugin.icon_url}" alt="${plugin.name}" class="plugin-icon"
                      onerror="this.style.display='none';this.parentElement.innerHTML='<div class=\\'plugin-icon-placeholder\\'><i class=\\'fas fa-puzzle-piece\\'></i></div>'">`;
    } else {
        iconHtml = `<div class="plugin-icon-placeholder"><i class="fas fa-puzzle-piece"></i></div>`;
    }

    const statusDot = plugin.is_installed
        ? `<span class="plugin-status-dot ${plugin.is_running ? 'running' : 'stopped'}"></span>`
        : '';

    let tags = '';
    if (plugin.is_installed) {
        tags += `<span class="tag tag-installed"><i class="fas fa-check"></i> Установлен</span>`;
        if (plugin.is_running) {
            tags += `<span class="tag tag-running"><i class="fas fa-play"></i> Запущен</span>`;
        } else {
            tags += `<span class="tag tag-stopped"><i class="fas fa-pause"></i> Остановлен</span>`;
        }
        if (plugin.has_update) {
            tags += `<span class="tag tag-update"><i class="fas fa-sync-alt fa-spin"></i> Обновление</span>`;
        }
    } else {
        tags += `<span class="tag tag-available"><i class="fas fa-download"></i> Доступен</span>`;
    }

    let actions = '';

    if (plugin.is_installed) {
        if (plugin.is_running) {
            actions += `<button onclick="stopPlugin('${plugin.id}')" class="btn btn-danger btn-sm">
                <i class="fas fa-stop"></i> Остановить
            </button>`;
        } else {
            actions += `<button onclick="startPlugin('${plugin.id}')" class="btn btn-success btn-sm">
                <i class="fas fa-play"></i> Запустить
            </button>`;
        }
        actions += `<button onclick="openConfig('${plugin.id}')" class="btn btn-secondary btn-sm">
            <i class="fas fa-sliders-h"></i>
        </button>`;
        actions += `<button onclick="uninstallPlugin('${plugin.id}')" class="btn btn-danger btn-sm">
            <i class="fas fa-trash-alt"></i>
        </button>`;
        if (plugin.has_update) {
            actions += `<button onclick="updatePlugin('${plugin.id}', '${plugin.download_url || ''}')" class="btn btn-warning btn-sm">
                <i class="fas fa-sync-alt"></i>
            </button>`;
        }
    } else {
        actions += `<button onclick="installPlugin('${plugin.id}', '${plugin.download_url}')" class="btn btn-primary btn-sm">
            <i class="fas fa-download"></i> Установить
        </button>`;
    }

    const cardClass = plugin.is_running ? 'plugin-card running' : 'plugin-card';

    return `
        <div class="${cardClass}">
            <div class="plugin-card-header">
                <div class="plugin-icon-wrapper">
                    ${iconHtml}
                    ${statusDot}
                </div>
                <div class="plugin-info">
                    <div class="plugin-name-row">
                        <span class="plugin-name">${plugin.name}</span>
                        <span class="plugin-version-badge">v${plugin.version}</span>
                    </div>
                    <div class="plugin-author">
                        <i class="fas fa-user-circle"></i>
                        <span>${plugin.author}</span>
                    </div>
                </div>
            </div>
            <div class="plugin-description">${plugin.description || 'Описание отсутствует'}</div>
            <div class="plugin-tags">${tags}</div>
            <div class="plugin-actions">${actions}</div>
        </div>
    `;
}

// ========== Действия с плагинами ==========
function installPlugin(id, url) {
    if (!confirm(`Установить плагин "${id}"?`)) return;

    fetch('/api/install', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id, download_url: url})
    })
    .then(res => res.json())
    .then(data => {
        showToast(data.message, data.success ? 'success' : 'error');
        if (data.success) loadPlugins();
    })
    .catch(error => showToast('Ошибка: ' + error.message, 'error'));
}

function uninstallPlugin(id) {
    if (!confirm(`Удалить плагин "${id}"? Это действие нельзя отменить.`)) return;

    fetch('/api/uninstall', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id})
    })
    .then(res => res.json())
    .then(data => {
        showToast(data.message, data.success ? 'success' : 'error');
        if (data.success) loadPlugins();
    })
    .catch(error => showToast('Ошибка: ' + error.message, 'error'));
}

function startPlugin(id) {
    fetch('/api/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id})
    })
    .then(res => res.json())
    .then(data => {
        showToast(data.message, data.success ? 'success' : 'error');
        if (data.success) loadPlugins();
    })
    .catch(error => showToast('Ошибка: ' + error.message, 'error'));
}

function stopPlugin(id) {
    fetch('/api/stop', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id})
    })
    .then(res => res.json())
    .then(data => {
        showToast(data.message, data.success ? 'success' : 'error');
        if (data.success) loadPlugins();
    })
    .catch(error => showToast('Ошибка: ' + error.message, 'error'));
}

function updatePlugin(id, url) {
    if (!confirm(`Обновить плагин "${id}"?`)) return;

    fetch('/api/update', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id, download_url: url})
    })
    .then(res => res.json())
    .then(data => {
        showToast(data.message, data.success ? 'success' : 'error');
        if (data.success) loadPlugins();
    })
    .catch(error => showToast('Ошибка: ' + error.message, 'error'));
}

function checkAllUpdates() {
    showToast('Проверка обновлений...', 'info');
    fetch('/api/check_updates')
        .then(res => res.json())
        .then(data => {
            if (data.count > 0) {
                showToast(`🔄 Найдено ${data.count} обновлений!`, 'success');
                loadPlugins();
            } else {
                showToast('✅ Все плагины актуальны!', 'success');
            }
        })
        .catch(error => showToast('Ошибка: ' + error.message, 'error'));
}

function rescanPlugins() {
    showToast('🔄 Сканирование папки plugins...', 'info');
    fetch('/api/rescan')
        .then(res => res.json())
        .then(data => {
            showToast(data.message, 'success');
            loadPlugins();
        })
        .catch(error => showToast('Ошибка: ' + error.message, 'error'));
}

function shutdownApp() {
    if (confirm('Закрыть Komit? Все запущенные плагины будут остановлены.')) {
        showToast('🔄 Завершение работы...', 'info');
        fetch('/api/shutdown', {
            method: 'POST'
        })
        .then(() => {
            // Ждем завершения
            setTimeout(() => {
                window.close();
            }, 1000);
        })
        .catch(() => {
            window.close();
        });
    }
}

// ========== Конфиг ==========
function openConfig(pluginId) {
    configPluginId = pluginId;
    document.getElementById('configTitle').textContent = `Конфигурация: ${pluginId}`;

    fetch(`/api/config/${pluginId}`)
        .then(res => res.json())
        .then(data => {
            let content = data.exists
                ? JSON.stringify(data.config, null, 2)
                : '{\n  "message": "Нет конфигурации"\n}';
            document.getElementById('configEditor').value = content;
            document.querySelector('.modal').classList.add('active');
        })
        .catch(error => showToast('Ошибка: ' + error.message, 'error'));
}

function closeConfig() {
    document.querySelector('.modal').classList.remove('active');
    configPluginId = null;
}

function formatConfig() {
    try {
        const content = document.getElementById('configEditor').value;
        const parsed = JSON.parse(content);
        document.getElementById('configEditor').value = JSON.stringify(parsed, null, 2);
        showToast('✅ Отформатировано', 'success');
    } catch (e) {
        showToast('❌ Ошибка: ' + e.message, 'error');
    }
}

function saveConfig() {
    if (!configPluginId) return;

    try {
        const config = JSON.parse(document.getElementById('configEditor').value);

        fetch(`/api/config/${configPluginId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        })
        .then(res => res.json())
        .then(data => {
            showToast(data.message, data.success ? 'success' : 'error');
            if (data.success) closeConfig();
        })
        .catch(error => showToast('Ошибка: ' + error.message, 'error'));
    } catch (e) {
        showToast('❌ Ошибка в JSON: ' + e.message, 'error');
    }
}

// ========== Toast уведомления ==========
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        info: 'fa-info-circle'
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<i class="fas ${icons[type] || icons.info}"></i> ${message}`;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(40px)';
        setTimeout(() => toast.remove(), 400);
    }, 4000);
}

// ========== Вспомогательные ==========
function showLoading() {
    document.getElementById('pluginsContainer').innerHTML = `
        <div class="loading-state">
            <div class="loading-spinner"></div>
            <p>Загрузка плагинов...</p>
        </div>
    `;
}

// Управление через клавиатуру
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (document.querySelector('.modal.active')) closeConfig();
    }
});