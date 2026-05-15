import { createConfigurationFeature } from './configuration.js';

const API_BASE = '/api';

const state = {
    currentPage: 'dashboard',
    documents: [],
    reports: [],
    selectedFiles: [],
    selectedFileDescriptions: [],
    deleteDocId: null,
    deleteFolderName: null,
    currentReportId: null,

    switchPage(page) {
        this.currentPage = page;
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.page === page);
        });
        document.querySelectorAll('.page').forEach(el => {
            el.classList.toggle('active', el.id === `${page}-page`);
        });
        const titles = {
            dashboard: 'Dashboard',
            documents: 'Document Management',
            reports: 'Report Management',
            configuration: 'System Configuration'
        };
        const pageTitle = document.getElementById('page-title');
        if (pageTitle) {
            pageTitle.textContent = titles[page] || 'Dashboard';
        }

        if (page === 'documents') {
            loadDocuments();
            loadDocumentStats();
            loadFoldersList();
        } else if (page === 'reports') {
            loadReportStats();
            loadReports();
        } else if (page === 'dashboard') {
            loadDashboardStats();
            loadRecentActivity();
        } else if (page === 'configuration') {
            loadConfiguration();
        }
    },

    openModal(id) {
        document.getElementById(id)?.classList.add('active');
    },

    closeModal(id) {
        document.getElementById(id)?.classList.remove('active');
    },

    showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        const icons = {
            success: 'fas fa-check-circle',
            error: 'fas fa-times-circle',
            info: 'fas fa-info-circle',
            warning: 'fas fa-exclamation-triangle'
        };
        toast.innerHTML = `
            <i class="${icons[type] || icons.info}"></i>
            <div class="toast-message">${message}</div>
        `;
        document.getElementById('toast-container')?.appendChild(toast);
        setTimeout(() => {
            toast.style.animation = 'fadeOut 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
};

window.state = state;

const {
    loadConfiguration,
    saveConfiguration,
    restartServer,
    testLLMConnection,
    togglePassword,
} = createConfigurationFeature({
    API_BASE,
    showToast: state.showToast.bind(state),
});

document.addEventListener('DOMContentLoaded', async () => {
    const authenticated = await checkAuth();
    if (!authenticated) return;

    initializeNavigation();
    initializeFileUpload();
    initializeFilters();
    initializeModals();
    initializeDocImprove();

    await Promise.all([
        loadDashboardStats(),
        loadDocumentStats(),
        loadDocuments(),
        loadReportStats(),
        loadReports(),
        loadFoldersForUpload(),
        loadFoldersList(),
        loadRecentActivity()
    ]);
});

function initializeDocImprove() {
    const runBtn = document.getElementById('doc-improve-btn');
    if (!runBtn) return;

    runBtn.addEventListener('click', runDocImprove);

    const refInput = document.getElementById('doc-improve-ref');
    refInput?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            runDocImprove();
        }
    });
}

async function runDocImprove() {
    const runBtn = document.getElementById('doc-improve-btn');
    const refEl = document.getElementById('doc-improve-ref');
    const goalEl = document.getElementById('doc-improve-goal');
    const topkEl = document.getElementById('doc-improve-topk');
    const outEl = document.getElementById('doc-improve-output');

    const documentRef = (refEl?.value || '').trim();
    const goal = (goalEl?.value || 'policy').trim() || 'policy';
    const topK = parseInt((topkEl?.value || '3').toString(), 10) || 3;

    if (!documentRef) {
        state.showToast('Please enter document reference (e.g. personal#9)', 'warning');
        return;
    }

    if (outEl) {
        outEl.textContent = 'Running analysis...';
    }

    if (runBtn) {
        runBtn.disabled = true;
        runBtn.dataset.originalText = runBtn.innerHTML;
        runBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyzing...';
    }

    try {
        const response = await fetch(`${API_BASE}/admin/doc-improve`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                document_ref: documentRef,
                goal,
                top_k: topK,
            }),
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok || !data.success) {
            const msg = data.error || `Request failed (${response.status})`;
            if (outEl) outEl.textContent = msg;
            state.showToast(msg, 'error');
            return;
        }

        if (outEl) {
            outEl.textContent = (data.report_markdown || '').trim() || '(Empty report)';
        }
        state.showToast(`Generated improvement report (${data.improve_id || 'ok'})`, 'success');
    } catch (error) {
        console.error('doc-improve failed:', error);
        const msg = error?.message || 'Unexpected error';
        if (outEl) outEl.textContent = msg;
        state.showToast(msg, 'error');
    } finally {
        if (runBtn) {
            runBtn.disabled = false;
            runBtn.innerHTML = runBtn.dataset.originalText || '<i class="fas fa-magic"></i> Analyze & Suggest';
        }
    }
}

// Expose functions for inline onclick handlers in admin_index.html
window.logout = logout;
window.togglePassword = togglePassword;
window.testLLMConnection = testLLMConnection;
window.loadConfiguration = loadConfiguration;
window.saveConfiguration = saveConfiguration;
window.restartServer = restartServer;
window.resolveReport = resolveReport;
window.deleteDocument = deleteDocument;
window.deleteFolder = deleteFolder;
window.renameFolder = renameFolder;
window.renameDocument = renameDocument;
window.removeFile = removeFile;
window.toggleOptionsMenu = toggleOptionsMenu;
window.showDeleteFolderConfirm = showDeleteFolderConfirm;
window.showRenameFolderModal = showRenameFolderModal;
window.viewReport = viewReport;
window.closeOptionsMenus = closeOptionsMenus;
window.toggleAdminPin = toggleAdminPin;
window.showRenameDocumentModal = showRenameDocumentModal;
window.showDeleteConfirm = showDeleteConfirm;

async function checkAuth() {
    try {
        // Use cookie-based session validation. Cookies are set HttpOnly by the server
        // so don't attempt to read them from JS; instead include credentials so the
        // browser sends the cookie and the server can validate it.
        const response = await fetch(`${API_BASE}/auth/validate`, {
            credentials: 'include'
        });

        if (!response.ok) {
            window.location.href = '/login';
            return false;
        }

        const data = await response.json();
        if (!data.success || data.user?.role !== 'admin') {
            window.location.href = '/login';
            return false;
        }

        const usernameEl = document.getElementById('admin-username');
        if (usernameEl) {
            usernameEl.textContent = data.user.full_name || data.user.username;
        }
        localStorage.setItem('last_user_id', data.user.id.toString());
        return true;
    } catch (error) {
        console.error('Auth check failed:', error);
        window.location.href = '/login';
        return false;
    }
}

function getSessionToken() {
    const value = `; ${document.cookie}`;
    const parts = value.split('; session_token=');
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
}

function initializeNavigation() {
    const sidebar = document.querySelector('.sidebar');
    const mainContent = document.querySelector('.main-content');
    const toggle = document.getElementById('sidebar-toggle');

    toggle?.addEventListener('click', () => {
        sidebar?.classList.toggle('collapsed');
        mainContent?.classList.toggle('expanded');
    });

    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            state.switchPage(item.dataset.page);
            if (window.innerWidth < 992) {
                sidebar?.classList.add('collapsed');
                mainContent?.classList.add('expanded');
            }
        });
    });

    window.addEventListener('resize', () => {
        if (window.innerWidth >= 992) {
            sidebar?.classList.remove('collapsed');
            mainContent?.classList.remove('expanded');
        }
    });
    
    // Initialize tab navigation
    initializeTabs();
}

function initializeTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;
            
            // Update tab buttons
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Update tab content
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            document.getElementById(tabId)?.classList.add('active');
        });
    });
}

function initializeFileUpload() {
    const fileInput = document.getElementById('file-input');
    const uploadArea = document.getElementById('upload-area');
    const uploadBtn = document.getElementById('upload-btn');

    fileInput?.addEventListener('change', handleFileSelect);
    uploadBtn?.addEventListener('click', uploadFiles);

    uploadArea?.addEventListener('dragover', event => {
        event.preventDefault();
        uploadArea.classList.add('drag-over');
    });

    uploadArea?.addEventListener('dragleave', () => uploadArea.classList.remove('drag-over'));
    uploadArea?.addEventListener('drop', event => {
        event.preventDefault();
        uploadArea.classList.remove('drag-over');
        handleFiles(event.dataTransfer.files);
    });
}

function initializeFilters() {
    document.getElementById('report-filter')?.addEventListener('change', event => {
        loadReports(event.target.value);
    });

    document.getElementById('documents-folder-filter')?.addEventListener('change', () => {
        loadDocuments();
    });
}

function initializeModals() {
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', event => {
            if (event.target === modal) {
                modal.classList.remove('active');
            }
        });
    });
}

function handleFileSelect(event) {
    handleFiles(event.target.files);
}

function handleFiles(fileList) {
    state.selectedFiles = Array.from(fileList || []);
    state.selectedFileDescriptions = state.selectedFiles.map(() => '');
    displaySelectedFiles();
}

function displaySelectedFiles() {
    const container = document.getElementById('selected-files');
    const uploadBtn = document.getElementById('upload-btn');

    if (!container || !uploadBtn) return;

    if (!state.selectedFiles.length) {
        container.innerHTML = '';
        uploadBtn.disabled = true;
        uploadBtn.innerHTML = '<i class="fas fa-upload"></i> Upload Selected Files';
        return;
    }

    container.innerHTML = state.selectedFiles.map((file, index) => `
        <div class="file-item">
            <div class="file-item-info">
                <i class="fas fa-file"></i>
                <span class="file-item-name">${file.name}</span>
                <span class="file-item-size">(${formatFileSize(file.size)})</span>
            </div>
            <div class="file-item-description" style="margin-top: 8px; width: 100%;">
                <input
                    type="text"
                    class="form-control"
                    placeholder="Mô tả cho tài liệu này (bắt buộc)"
                    value="${escapeHtml(state.selectedFileDescriptions[index] || '')}"
                    oninput="updateFileDescription(${index}, this.value)"
                />
            </div>
            <button class="file-item-remove" onclick="removeFile(${index})">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `).join('');

    uploadBtn.disabled = !areAllFileDescriptionsPresent();
}

function areAllFileDescriptionsPresent() {
    if (!state.selectedFiles.length) return false;
    return state.selectedFileDescriptions.length === state.selectedFiles.length
        && state.selectedFileDescriptions.every(d => typeof d === 'string' && d.trim().length > 0);
}

function updateFileDescription(index, value) {
    state.selectedFileDescriptions[index] = value;
    const uploadBtn = document.getElementById('upload-btn');
    if (uploadBtn) uploadBtn.disabled = !areAllFileDescriptionsPresent();
}

window.updateFileDescription = updateFileDescription;

function removeFile(index) {
    state.selectedFiles.splice(index, 1);
    state.selectedFileDescriptions.splice(index, 1);
    displaySelectedFiles();
}

async function loadFoldersForUpload() {
    try {
        const response = await fetch(`${API_BASE}/documents/folders`, {
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            const folders = data.folders || [];
            
            const folderSelect = document.getElementById('folder-select');
            if (folderSelect) {
                folderSelect.innerHTML = folders.map(folder => 
                    `<option value="${folder.name}">${folder.name}</option>`
                ).join('');
            }

            const filterSelect = document.getElementById('documents-folder-filter');
            if (filterSelect) {
                const current = filterSelect.value;
                filterSelect.innerHTML = `<option value="">All Folders</option>` + folders
                    .map(folder => `<option value="${folder.name}">${folder.name}</option>`)
                    .join('');
                filterSelect.value = current;
            }
        }
    } catch (error) {
        console.error('Error loading folders for upload:', error);
    }
}

async function uploadFiles() {
    if (!state.selectedFiles.length) {
        state.showToast('Please select files to upload', 'warning');
        return;
    }

    if (!areAllFileDescriptionsPresent()) {
        state.showToast('Vui lòng nhập mô tả cho từng file trước khi upload', 'warning');
        return;
    }

    const uploadBtn = document.getElementById('upload-btn');
    uploadBtn.disabled = true;
    uploadBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading...';

    const formData = new FormData();
    const folderSelect = document.getElementById('folder-select');
    const newFolderInput = document.getElementById('new-folder-input');
    
    // Use new folder name if provided, otherwise use selected folder
    const selectedFolder = (newFolderInput && newFolderInput.value.trim()) 
        ? newFolderInput.value.trim() 
        : (folderSelect ? folderSelect.value : 'Chung');
    
    formData.append('folder', selectedFolder);
    state.selectedFiles.forEach((file, index) => {
        formData.append('files', file);
        formData.append('descriptions', (state.selectedFileDescriptions[index] || '').trim());
    });

    try {
        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            credentials: 'include',
            body: formData
        });
        const data = await response.json();
        if (!response.ok || data.success === false) {
            throw new Error(data.error || 'Upload failed');
        }
        state.showToast(`Uploaded ${data.uploaded || state.selectedFiles.length} file(s)`, 'success');
        state.selectedFiles = [];
        state.selectedFileDescriptions = [];
        displaySelectedFiles();
        if (newFolderInput) newFolderInput.value = '';
        await Promise.all([loadDocuments(), loadDocumentStats(), loadDashboardStats(), loadFoldersForUpload()]);
    } catch (error) {
        console.error('Upload error:', error);
        state.showToast(error.message, 'error');
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.innerHTML = '<i class="fas fa-upload"></i> Upload Selected Files';
    }
}

async function loadDashboardStats() {
    try {
        const response = await fetch(`${API_BASE}/stats`, { credentials: 'include' });
        const data = await response.json();
        const stats = data.stats || data || {};

        setText('dash-total-docs', stats.total_documents ?? 0);
        setText('dash-total-storage', formatBytes(stats.total_storage || 0));
        setText('dash-pending-reports', stats.pending_reports ?? 0);
        setText('dash-last-upload', stats.last_upload ? formatDate(stats.last_upload) : 'Never');
    updateBadges(stats.pending_reports ?? 0);
    } catch (error) {
        console.error('Dashboard stats error:', error);
    }
}

async function loadDocumentStats() {
    try {
        const response = await fetch(`${API_BASE}/stats`, { credentials: 'include' });
        const data = await response.json();
        const stats = data.stats || data || {};
        setText('doc-total-docs', stats.total_documents ?? 0);
        setText('doc-total-storage', formatBytes(stats.total_storage || 0));
        setText('doc-last-upload', stats.last_upload ? formatDate(stats.last_upload) : 'Never');
    } catch (error) {
        console.error('Document stats error:', error);
    }
}

async function loadDocuments() {
    const tbody = document.getElementById('documents-table-body');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="6" class="text-center">Loading...</td></tr>';
    try {
        const folderFilter = (document.getElementById('documents-folder-filter')?.value || '').trim();
        const params = new URLSearchParams();
        if (folderFilter) params.set('folder', folderFilter);
        const url = params.toString() ? `${API_BASE}/documents?${params.toString()}` : `${API_BASE}/documents`;

        const response = await fetch(url, { credentials: 'include' });
        const data = await response.json();
        const documents = Array.isArray(data) ? data : data.documents || [];
        state.documents = documents;

        if (!documents.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No documents found</td></tr>';
            return;
        }

        tbody.innerHTML = documents.map(doc => {
            const displayName = cleanFilename(doc.original_filename || doc.filename);
            const folderName = doc.folder || 'Chung';
            const isPinned = doc.admin_pinned === 1;
            const pinIcon = isPinned ? 'fa-thumbtack' : 'fa-thumbtack';
            const pinText = isPinned ? 'Bỏ ghim' : 'Ghim';
            const pinClass = isPinned ? 'pinned' : '';
            return `
            <tr class="${pinClass}">
                <td>${doc.id}</td>
                <td>
                    ${isPinned ? '<i class="fas fa-thumbtack" style="color: #f6c23e; margin-right: 6px;" title="Đã ghim bởi admin"></i>' : ''}
                    ${escapeHtml(displayName)}
                </td>
                <td><span class="folder-badge"><i class="fas fa-folder"></i> ${escapeHtml(folderName)}</span></td>
                <td>${formatFileSize(doc.file_size || 0)}</td>
                <td>${formatDate(doc.upload_date)}</td>
                <td style="text-align:center;">
                    <div class="options-menu-wrapper">
                        <button class="btn btn-secondary btn-sm options-btn" onclick="toggleOptionsMenu(this)">
                            <i class="fas fa-ellipsis-v"></i>
                        </button>
                        <div class="options-dropdown">
                            <div class="options-item" onclick="closeOptionsMenus(); toggleAdminPin(${doc.id}, ${isPinned})">
                                <i class="fas ${pinIcon}"></i> ${pinText}
                            </div>
                            <div class="options-item" onclick="closeOptionsMenus(); showRenameDocumentModal(${doc.id}, '${escapeHtml(displayName.replace(/'/g, "&apos;"))}')">
                                <i class="fas fa-edit"></i> Đổi tên
                            </div>
                            <div class="options-item delete" onclick="closeOptionsMenus(); showDeleteConfirm(${doc.id}, '${escapeHtml(displayName.replace(/'/g, "&apos;"))}')">
                                <i class="fas fa-trash"></i> Xóa
                            </div>
                        </div>
                    </div>
                </td>
            </tr>
        `}).join('');
    } catch (error) {
        console.error('Documents error:', error);
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Error loading documents</td></tr>';
    }
}

function toggleOptionsMenu(btn) {
    const dropdown = btn.nextElementSibling;
    const wasOpen = dropdown.classList.contains('show');
    closeOptionsMenus();
    if (!wasOpen) {
        dropdown.classList.add('show');
    }
}

function closeOptionsMenus() {
    document.querySelectorAll('.options-dropdown.show').forEach(d => d.classList.remove('show'));
}

document.addEventListener('click', (e) => {
    if (!e.target.closest('.options-menu-wrapper')) {
        closeOptionsMenus();
    }
});

async function toggleAdminPin(docId, isPinned) {
    const action = isPinned ? 'admin-unpin' : 'admin-pin';
    try {
        const response = await fetch(`${API_BASE}/documents/${docId}/${action}`, {
            method: 'POST',
            credentials: 'include'
        });
        const data = await response.json();
        if (!response.ok || data.success === false) {
            throw new Error(data.error || 'Failed to update pin status');
        }
        state.showToast(isPinned ? 'Document unpinned' : 'Document pinned', 'success');
        await loadDocuments();
    } catch (error) {
        console.error('Pin error:', error);
        state.showToast(error.message, 'error');
    }
}

function showDeleteConfirm(docId, name) {
    state.deleteDocId = docId;
    setText('delete-doc-name', name || 'Selected document');
    state.openModal('delete-modal');
}

function showRenameDocumentModal(docId, currentName) {
    state.renameDocId = docId;
    document.getElementById('rename-doc-old-name').value = currentName;
    document.getElementById('rename-doc-new-name').value = currentName;
    state.openModal('rename-document-modal');
}

async function renameDocument() {
    if (!state.renameDocId) return;

    const newName = document.getElementById('rename-doc-new-name').value.trim();
    if (!newName) {
        state.showToast('Please enter a new name', 'error');
        return;
    }

    const saveBtn = document.querySelector('#rename-document-modal .btn-primary');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    try {
        const response = await fetch(`${API_BASE}/documents/${state.renameDocId}/rename`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName })
        });
        const data = await response.json();
        if (!response.ok || data.success === false) {
            throw new Error(data.error || 'Failed to rename document');
        }
        state.showToast('Document renamed successfully', 'success');
        state.closeModal('rename-document-modal');
        state.renameDocId = null;
        await loadDocuments();
    } catch (error) {
        console.error('Rename error:', error);
        state.showToast(error.message, 'error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="fas fa-save"></i> Save';
    }
}

async function deleteDocument() {
    if (!state.deleteDocId) return;
    const deleteBtn = document.querySelector('#delete-modal .btn-danger');
    deleteBtn.disabled = true;
    deleteBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Deleting...';

    try {
        const response = await fetch(`${API_BASE}/documents/${state.deleteDocId}`, {
            method: 'DELETE',
            credentials: 'include'
        });
        const data = await response.json();
        if (!response.ok || data.success === false) {
            throw new Error(data.error || 'Failed to delete document');
        }
        state.showToast('Document deleted', 'success');
        state.closeModal('delete-modal');
        state.deleteDocId = null;
        await Promise.all([loadDocuments(), loadDocumentStats(), loadDashboardStats()]);
    } catch (error) {
        console.error('Delete error:', error);
        state.showToast(error.message, 'error');
    } finally {
        deleteBtn.disabled = false;
        deleteBtn.innerHTML = '<i class="fas fa-trash"></i> Delete';
    }
}

async function loadReportStats() {
    try {
        const response = await fetch(`${API_BASE}/stats`, { credentials: 'include' });
        const data = await response.json();
        const stats = data.stats || data || {};
        setText('rep-total-reports', stats.total_reports ?? 0);
        setText('rep-pending-reports', stats.pending_reports ?? 0);
        setText('rep-resolved-reports', stats.resolved_reports ?? 0);
    } catch (error) {
        console.error('Report stats error:', error);
    }
}

async function loadReports(status = null) {
    const tbody = document.getElementById('reports-table-body');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="6" class="text-center">Loading...</td></tr>';

    const filter = status || document.getElementById('report-filter')?.value || 'all';
    const params = new URLSearchParams();
    if (filter !== 'all') {
        params.set('status', filter);
    }

    try {
        const response = await fetch(`${API_BASE}/reports?${params.toString()}`, { credentials: 'include' });
        const data = await response.json();
        if (!response.ok || data.success === false) {
            throw new Error(data.error || 'Failed to load reports');
        }
        const reports = data.reports || [];
        state.reports = reports;

        if (!reports.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No reports found</td></tr>';
            return;
        }

        tbody.innerHTML = reports.map(report => `
            <tr>
                <td>${report.id}</td>
                <td>${escapeHtml(report.report_type || 'general')}</td>
                <td>${escapeHtml(truncateText(report.description || report.report_reason || '', 80))}</td>
                <td>${formatDate(report.report_date || report.created_at)}</td>
                <td>
                    <span class="status-badge ${report.status === 'resolved' ? 'status-resolved' : 'status-pending'}">
                        ${report.status}
                    </span>
                </td>
                <td style="text-align:center;">
                    <button class="btn btn-primary btn-sm" onclick="viewReport(${report.id})">
                        <i class="fas fa-eye"></i> View
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Reports error:', error);
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Failed to load reports</td></tr>';
    }
}

async function viewReport(reportId) {
    try {
        const response = await fetch(`${API_BASE}/reports/${reportId}`, { credentials: 'include' });
        const data = await response.json();
        if (!response.ok || data.success === false) {
            throw new Error(data.error || 'Failed to load report');
        }
        const report = data.report || data;
        state.currentReportId = reportId;

        const detail = document.getElementById('report-detail-body');
        detail.innerHTML = `
            <div style="margin-bottom:15px;"><strong>Report ID:</strong> ${report.id}</div>
            <div style="margin-bottom:15px;"><strong>Type:</strong> ${escapeHtml(report.report_type || 'general')}</div>
            <div style="margin-bottom:15px;"><strong>User Question:</strong><br>
                <div class="detail-box">${escapeHtml(report.question || 'N/A')}</div>
            </div>
            <div style="margin-bottom:15px;"><strong>AI Answer:</strong><br>
                <div class="detail-box warning">${escapeHtml(report.answer || 'N/A')}</div>
            </div>
            <div style="margin-bottom:15px;"><strong>User Comment:</strong><br>
                <div class="detail-box danger">${escapeHtml(report.user_comment || report.description || 'No additional comment')}</div>
            </div>
            <div style="margin-bottom:15px;"><strong>Status:</strong>
                <span class="status-badge ${report.status === 'resolved' ? 'status-resolved' : 'status-pending'}">${report.status}</span>
            </div>
            ${report.resolution_notes ? `<div style="margin-bottom:15px;"><strong>Resolution Notes:</strong><br><div class="detail-box success">${escapeHtml(report.resolution_notes)}</div></div>` : ''}
        `;

        const resolveBtn = document.getElementById('resolve-btn');
        if (resolveBtn) {
            resolveBtn.style.display = report.status === 'resolved' ? 'none' : 'inline-flex';
        }

        state.openModal('report-modal');
    } catch (error) {
        console.error('View report error:', error);
        state.showToast(error.message, 'error');
    }
}

async function resolveReport() {
    if (!state.currentReportId) return;

    const resolution = prompt('What action did you take to resolve this report?', 'Updated supporting documents');
    if (!resolution) return;

    const resolveBtn = document.getElementById('resolve-btn');
    resolveBtn.disabled = true;
    resolveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';

    try {
        const response = await fetch(`${API_BASE}/reports/${state.currentReportId}/resolve`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ resolution_notes: resolution })
        });
        const data = await response.json();
        if (!response.ok || data.success === false) {
            throw new Error(data.error || 'Failed to resolve report');
        }
        state.showToast('Report resolved', 'success');
        state.closeModal('report-modal');
        state.currentReportId = null;
        await Promise.all([loadReports(), loadReportStats(), loadDashboardStats()]);
    } catch (error) {
        console.error('Resolve error:', error);
        state.showToast(error.message, 'error');
    } finally {
        resolveBtn.disabled = false;
        resolveBtn.innerHTML = '<i class="fas fa-check"></i> Mark as Resolved';
    }
}

async function logout() {
    try {
        await fetch(`${API_BASE}/auth/logout`, {
            method: 'POST',
            credentials: 'include'
        });
    } finally {
        document.cookie = 'session_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/;';
        window.location.href = '/login';
    }
}

function updateBadges(pendingReports) {
    const reportBadge = document.getElementById('sidebar-badge');
    const notification = document.getElementById('notification-badge');

    toggleBadge(reportBadge, pendingReports);
    toggleBadge(notification, pendingReports);
}

function toggleBadge(element, value) {
    if (!element) return;
    if (value > 0) {
        element.textContent = value;
        element.style.display = 'inline-block';
    } else {
        element.style.display = 'none';
    }
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = value;
    }
}

function formatBytes(bytes) {
    if (!bytes) return '0 MB';
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes || 1) / Math.log(1024));
    const value = bytes / Math.pow(1024, i);
    return `${value.toFixed(1)} ${sizes[i]}`;
}

function formatFileSize(bytes) {
    if (!bytes) return '0 MB';
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${sizes[i]}`;
}

function formatDate(value) {
    if (!value) return 'Unknown';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
}

function truncateText(text, length) {
    if (!text) return '';
    return text.length > length ? `${text.slice(0, length)}…` : text;
}

function escapeHtml(str = '') {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Strip hash prefix from filename (e.g., "abc123def456_filename.pdf" -> "filename.pdf")
function cleanFilename(filename) {
    if (!filename) return '';
    // Match 32-character hex prefix followed by underscore
    return filename.replace(/^[a-f0-9]{32}_/i, '');
}

// ============================================================
// Folder Management Functions
// ============================================================

async function loadFoldersList() {
    const tbody = document.getElementById('folders-table-body');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="4" class="text-center">Loading...</td></tr>';

    try {
        const response = await fetch(`${API_BASE}/documents/folders`, { credentials: 'include' });
        const data = await response.json();
        const folders = data.folders || [];

        if (!folders.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">No folders found</td></tr>';
            return;
        }

        tbody.innerHTML = folders.map(folder => `
            <tr>
                <td>${folder.id || '-'}</td>
                <td><i class="fas fa-folder"></i> ${escapeHtml(folder.name)}</td>
                <td>${folder.count || 0}</td>
                <td style="text-align:center;">
                    ${folder.name !== 'Chung' ? `
                        <button class="btn btn-primary btn-sm" onclick="showRenameFolderModal('${escapeHtml(folder.name.replace(/'/g, "\\'"))}')">
                            <i class="fas fa-edit"></i> Rename
                        </button>
                        <button class="btn btn-danger btn-sm" onclick="showDeleteFolderConfirm('${escapeHtml(folder.name.replace(/'/g, "\\'"))}')">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    ` : '<span class="text-muted">Default</span>'}
                </td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Folders list error:', error);
        tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Error loading folders</td></tr>';
    }
}

function showDeleteFolderConfirm(folderName) {
    state.deleteFolderName = folderName;
    setText('delete-folder-name', folderName);
    state.openModal('delete-folder-modal');
}

async function deleteFolder() {
    if (!state.deleteFolderName) return;
    
    const deleteBtn = document.querySelector('#delete-folder-modal .btn-danger');
    deleteBtn.disabled = true;
    deleteBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Deleting...';

    try {
        const response = await fetch(`${API_BASE}/documents/folders/delete`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_name: state.deleteFolderName })
        });
        const data = await response.json();
        if (!response.ok || data.success === false) {
            throw new Error(data.error || 'Failed to delete folder');
        }
        
        let message = `Folder "${state.deleteFolderName}" deleted`;
        if (data.documents_moved > 0) {
            message += ` (${data.documents_moved} documents moved to Chung)`;
        }
        state.showToast(message, 'success');
        state.closeModal('delete-folder-modal');
        state.deleteFolderName = null;
        await Promise.all([loadFoldersList(), loadFoldersForUpload(), loadDocuments(), loadRecentActivity()]);
    } catch (error) {
        console.error('Delete folder error:', error);
        state.showToast(error.message, 'error');
    } finally {
        deleteBtn.disabled = false;
        deleteBtn.innerHTML = '<i class="fas fa-trash"></i> Delete Folder';
    }
}

function showRenameFolderModal(folderName) {
    state.renameFolderOldName = folderName;
    document.getElementById('rename-folder-old-name').value = folderName;
    document.getElementById('rename-folder-new-name').value = '';
    state.openModal('rename-folder-modal');
}

async function renameFolder() {
    const newName = document.getElementById('rename-folder-new-name').value.trim();
    
    if (!newName) {
        state.showToast('Please enter a new folder name', 'error');
        return;
    }
    
    if (newName === state.renameFolderOldName) {
        state.showToast('New name is the same as current name', 'error');
        return;
    }
    
    const saveBtn = document.querySelector('#rename-folder-modal .btn-primary');
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';

    try {
        const response = await fetch(`${API_BASE}/documents/folders/rename`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                old_name: state.renameFolderOldName, 
                new_name: newName 
            })
        });
        const data = await response.json();
        if (!response.ok || data.success === false) {
            throw new Error(data.error || 'Failed to rename folder');
        }
        
        state.showToast(`Folder renamed to "${newName}"`, 'success');
        state.closeModal('rename-folder-modal');
        state.renameFolderOldName = null;
        await Promise.all([loadFoldersList(), loadFoldersForUpload(), loadDocuments(), loadRecentActivity()]);
    } catch (error) {
        console.error('Rename folder error:', error);
        state.showToast(error.message, 'error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="fas fa-save"></i> Save';
    }
}

// ============================================================
// Recent Activity Functions
// ============================================================

async function loadRecentActivity() {
    const container = document.getElementById('recent-activity-list');
    if (!container) return;
    
    container.innerHTML = '<tr><td colspan="3" class="text-muted">Loading activity...</td></tr>';
    
    try {
        const response = await fetch(`${API_BASE}/activity/recent`, { credentials: 'include' });
        const data = await response.json();
        
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to load activity');
        }
        
        const activities = data.activities || [];
        
        if (!activities.length) {
            container.innerHTML = '<tr><td colspan="3" class="text-muted">No recent activity</td></tr>';
            return;
        }
        
        container.innerHTML = activities.map(activity => {
            const activityName = getActivityName(activity.type);
            return `
                <tr>
                    <td>${escapeHtml(activityName)}</td>
                    <td>${escapeHtml(activity.description)}</td>
                    <td>${formatRelativeTime(activity.timestamp)}</td>
                </tr>
            `;
        }).join('');
    } catch (error) {
        console.error('Error loading recent activity:', error);
        container.innerHTML = '<tr><td colspan="3" class="text-muted">Failed to load activity</td></tr>';
    }
}

function getActivityName(activityType) {
    const names = {
        'document_uploaded': 'Document Upload',
        'document_deleted': 'Document Deleted',
        'folder_created': 'Folder Created',
        'folder_deleted': 'Folder Deleted',
        'folder_renamed': 'Folder Renamed',
        'report_resolved': 'Report Resolved',
        'report_submitted': 'Report Submitted',
        'news_fetched': 'News Fetched',
        'news_refresh': 'News Refresh',
        'user_login': 'User Login'
    };
    return names[activityType] || activityType;
}

function getActivityColor(activityType) {
    const colors = {
        'document_uploaded': 'green',
        'document_deleted': 'red',
        'folder_created': 'blue',
        'folder_deleted': 'orange',
        'report_resolved': 'green',
        'report_submitted': 'orange',
        'news_fetched': 'blue',
        'news_refresh': 'purple',
        'user_login': 'blue'
    };
    return colors[activityType] || 'gray';
}

function formatRelativeTime(timestamp) {
    if (!timestamp) return 'Unknown';
    
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return timestamp;
    
    const now = new Date();
    const diff = now - date;
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    
    if (seconds < 60) return 'Just now';
    if (minutes < 60) return `${minutes} minute${minutes !== 1 ? 's' : ''} ago`;
    if (hours < 24) return `${hours} hour${hours !== 1 ? 's' : ''} ago`;
    if (days < 7) return `${days} day${days !== 1 ? 's' : ''} ago`;
    
    return date.toLocaleDateString();
}

// ========================================
// Configuration Page Functions
// ========================================

