// Enhanced Technical Assistant - Complete JavaScript
// Version: 2025-12-02 - Vietnamese UI

const API_URL = window.location.origin + '/api';
let currentUser = null;
let currentRole = 'security_engineer'; // SET DEFAULT IMMEDIATELY
let chatHistory = [];
let activeSessionId = localStorage.getItem('chat_session_id') || null;
let selectedDocuments = [];
let newsCache = { role: null, articles: [], fetchedAt: 0 };
let newsRequestController = null;
let latestNewsFetchInFlight = false;
let personalDocsRetryCount = 0;
let newsRetryCount = 0;
const MAX_RETRIES = 3;

// Initialize app on load
document.addEventListener('DOMContentLoaded', function () {
    console.log('=== Technical Assistant Initializing ===');
    console.log('API_URL:', API_URL);
    console.log('Default role:', currentRole);

    // Update role badge immediately
    updateRoleBadge(currentRole);

    // Initialize tab visibility
    document.querySelectorAll('.tab-content').forEach(function (content) {
        if (content.classList.contains('active')) {
            content.style.display = 'block';
        } else {
            content.style.display = 'none';
        }
    });

    // Set up event listeners
    setupEventListeners();

    // Start all data loading immediately - don't wait for anything
    console.log('Starting data loads...');

    // Load user (async, don't wait)
    loadCurrentUser().then(function () {
        console.log('User loaded successfully');
    }).catch(function (e) {
        console.warn('User load failed:', e);
    });

    // Load role first, then load news with correct role
    loadUserRole().then(function () {
        console.log('Role loaded successfully, now loading news with role:', currentRole);
        // Load news AFTER role is loaded so it uses correct role
        loadNews({ force: true });
    }).catch(function (e) {
        console.warn('Role load failed:', e);
        // Still load news with default role
        loadNews({ force: true });
    });

    // Load all content immediately (except news which waits for role)
    console.log('Loading company documents...');
    loadCompanyDocuments();

    console.log('Loading personal documents...');
    loadPersonalDocuments();

    console.log('Loading pinned documents...');
    loadPinnedDocuments();

    console.log('Loading folders for upload dropdown...');
    loadFoldersForUpload();

    console.log('Loading chat history...');
    loadChatHistory();

    console.log('=== Initialization complete ===');
});

// Expose functions for inline onclick handlers in user_index.html
window.logout = logout;

function setupEventListeners() {
    // Sidebar toggle
    const sidebarToggle = document.getElementById('sidebarToggle');
    const leftSidebar = document.querySelector('.left-sidebar');
    if (sidebarToggle && leftSidebar) {
        sidebarToggle.addEventListener('click', () => {
            leftSidebar.classList.toggle('collapsed');
            sidebarToggle.classList.toggle('sidebar-hidden');
            // Store preference
            localStorage.setItem('sidebarCollapsed', leftSidebar.classList.contains('collapsed'));
        });
        // Restore preference
        if (localStorage.getItem('sidebarCollapsed') === 'true') {
            leftSidebar.classList.add('collapsed');
            sidebarToggle.classList.add('sidebar-hidden');
        }
    }

    // Tab navigation
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    // Section reload buttons
    document.querySelectorAll('.section-refresh').forEach(button => {
        button.addEventListener('click', async () => {
            const target = button.dataset.target;
            button.disabled = true;
            button.classList.add('spinning');
            try {
                if (target === 'personal-docs') {
                    await loadPersonalDocuments();
                } else if (target === 'pinned-docs') {
                    await loadPinnedDocuments();
                } else {
                    await loadCompanyDocuments();
                }
            } finally {
                button.disabled = false;
                button.classList.remove('spinning');
            }
        });
    });

    // Chat input
    const chatInput = document.getElementById('chatInput');
    const sendBtn = document.getElementById('sendButton');

    if (chatInput) {
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    sendBtn?.addEventListener('click', sendMessage);

    // News actions
    document.getElementById('refreshNews')?.addEventListener('click', refreshNews);
    document.getElementById('fetchLatestNews')?.addEventListener('click', () => fetchLatestNews({ reload: true }));

    // Upload form
    document.getElementById('uploadForm')?.addEventListener('submit', handleUpload);

    // Clear chat
    document.getElementById('clearChat')?.addEventListener('click', clearChat);
    document.getElementById('newsTimeFilter')?.addEventListener('change', () => {
        if (!renderNewsFromCache()) {
            loadNews();
        }
    });
    
    // Sort filter - needs fresh fetch from server
    document.getElementById('newsSortFilter')?.addEventListener('change', () => {
        loadNews({ force: true });
    });

    document.getElementById('clearSelectedDocs')?.addEventListener('click', (event) => {
        event.preventDefault();
        clearSelectedDocuments();
    });

    // Report modal
    document.getElementById('reportModalClose')?.addEventListener('click', closeReportModal);
    document.getElementById('submitReport')?.addEventListener('click', submitReport);
    
    // Close modal when clicking outside
    document.getElementById('reportModal')?.addEventListener('click', (e) => {
        if (e.target.id === 'reportModal') {
            closeReportModal();
        }
    });
}

// Tab Navigation
function switchTab(tabName) {
    console.log('Switching to tab:', tabName);
    const targetTab = document.querySelector(`.nav-tab[data-tab="${tabName}"]`);
    if (!targetTab) {
        console.warn(`Unknown tab requested: ${tabName}`);
        return;
    }

    // Update tab buttons
    document.querySelectorAll('.nav-tab').forEach(tab => {
        const isActive = tab.dataset.tab === tabName;
        tab.classList.toggle('active', isActive);
        tab.setAttribute('aria-selected', String(isActive));
    });

    // Update tab content - show matching, hide others
    document.querySelectorAll('.tab-content').forEach(content => {
        const shouldShow = content.id === `${tabName}-tab`;
        if (shouldShow) {
            content.classList.add('active');
            content.style.display = 'block';
            console.log(`Showing tab: ${content.id}`);
        } else {
            content.classList.remove('active');
            content.style.display = 'none';
        }
    });

    // Auto-refresh content when tab is switched to
    if (tabName === 'pinned') {
        loadPinnedDocuments();
    } else if (tabName === 'documents') {
        loadPersonalDocuments();
    }
}

function buildDocKey(type, id, filename) {
    const safeId = id ?? filename ?? 'unknown';
    return `${type}:${safeId}`;
}

function toggleDocumentSelection(docInfo) {
    const key = buildDocKey(docInfo.type, docInfo.id, docInfo.filename);
    const existingIndex = selectedDocuments.findIndex(doc => doc.key === key);

    if (existingIndex >= 0) {
        selectedDocuments.splice(existingIndex, 1);
        updateSelectedDocsUI();
        return false;
    }

    selectedDocuments.push({
        key,
        type: docInfo.type,
        id: docInfo.id,
        filename: docInfo.filename,
        label: docInfo.label
    });
    updateSelectedDocsUI();
    return true;
}

function removeSelectedDocument(key) {
    const index = selectedDocuments.findIndex(doc => doc.key === key);
    if (index >= 0) {
        selectedDocuments.splice(index, 1);
        updateSelectedDocsUI();
    }
}

function clearSelectedDocuments() {
    if (selectedDocuments.length === 0) return;
    selectedDocuments = [];
    updateSelectedDocsUI();
}

function updateSelectedDocsUI() {
    const bar = document.getElementById('selectedDocsBar');
    const list = document.getElementById('selectedDocsList');
    const clearBtn = document.getElementById('clearSelectedDocs');

    if (!bar || !list) return;

    if (selectedDocuments.length === 0) {
        bar.style.display = 'none';
        list.innerHTML = '';
        if (clearBtn) {
            clearBtn.style.display = 'none';
        }
    } else {
        bar.style.display = 'flex';
        list.innerHTML = '';
        selectedDocuments.forEach(doc => {
            const pill = document.createElement('div');
            pill.className = 'selected-doc-pill';

            const icon = document.createElement('i');
            icon.className = `fas ${doc.type === 'personal' ? 'fa-user' : 'fa-building'}`;
            const label = document.createElement('span');
            label.textContent = doc.label;

            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.innerHTML = '<i class="fas fa-times"></i>';
            removeBtn.addEventListener('click', (event) => {
                event.preventDefault();
                removeSelectedDocument(doc.key);
            });

            pill.appendChild(icon);
            pill.appendChild(label);
            pill.appendChild(removeBtn);
            list.appendChild(pill);
        });

        if (clearBtn) {
            clearBtn.style.display = 'flex';
        }
    }

    syncDocumentSelectionStyles();
}

function syncDocumentSelectionStyles() {
    const selectedKeys = new Set(selectedDocuments.map(doc => doc.key));
    document.querySelectorAll('.document-item').forEach(item => {
        const key = item.dataset.docKey;
        if (!key) return;
        const isSelected = selectedKeys.has(key);
        item.classList.toggle('selected', isSelected);
        const actionBtn = item.querySelector('.doc-action.doc-select');
        if (actionBtn) {
            actionBtn.classList.toggle('selected', isSelected);
            actionBtn.title = isSelected ? 'Đã chọn để trò chuyện' : 'Dùng tài liệu này để trò chuyện';
            const labelEl = actionBtn.querySelector('span');
            if (labelEl) {
                labelEl.textContent = isSelected ? 'Đã chọn' : 'Chọn';
            }
        }
    });
}

// User Management
async function loadCurrentUser() {
    try {
        // First try to validate session with backend (uses cookie automatically)
        const response = await fetch('/api/auth/validate', {
            credentials: 'include'
        });

        if (!response.ok) {
            console.warn('Not authenticated (status:', response.status, ')');
            // Set a default user for UI display
            currentUser = 'Guest';
            const displayElement = document.getElementById('username-display') || document.getElementById('user-name');
            if (displayElement) {
                displayElement.textContent = 'Guest User';
            }
            return null;
        }

        const data = await response.json();
        if (data.success && data.user) {
            // Store user info for display
            currentUser = data.user.username;
            localStorage.setItem('user_info', JSON.stringify(data.user));

            const displayElement = document.getElementById('username-display') || document.getElementById('user-name');
            if (displayElement) {
                displayElement.textContent = data.user.full_name || data.user.username;
            }

            console.log('User loaded:', currentUser);
            return currentUser;
        } else {
            console.warn('Invalid session response');
            currentUser = 'Guest';
            return null;
        }
    } catch (error) {
        console.error('Error validating session:', error);
        console.warn('Network error or server not responding');
        currentUser = 'Guest';
        return null;
    }
}

async function loadUserRole() {
    try {
        console.log('Loading user role...');
        // Call the /api/user/role endpoint to get technical role
        const response = await fetch(`${API_URL}/user/role`, {
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        console.log('Role response status:', response.status);

        if (response.ok) {
            const data = await response.json();
            console.log('Role data:', data);

            // Extract role from the response
            if (data.success && data.role) {
                let roleValue = data.role;

                // If roleValue is an object, extract the role_type
                if (roleValue && typeof roleValue === 'object') {
                    currentRole = roleValue.role_type || roleValue.role || 'security_engineer';
                } else if (roleValue && typeof roleValue === 'string') {
                    currentRole = roleValue;
                } else {
                    console.warn('No role found in response, using default');
                    currentRole = 'security_engineer';
                }

                console.log('Current role set to:', currentRole);
                updateRoleBadge(currentRole);
                setNewsStatus('Ready', 'idle');
            } else {
                console.warn('Invalid response structure, using default role');
                currentRole = 'security_engineer';
                updateRoleBadge(currentRole);
            }
        } else {
            console.error('Error loading user role, status:', response.status, '- using default');
            currentRole = 'security_engineer'; // Fallback
            updateRoleBadge(currentRole);
        }
        return currentRole;
    } catch (error) {
        console.error('Error loading user role:', error, '- using default');
        currentRole = 'security_engineer'; // Fallback
        updateRoleBadge(currentRole);
        return currentRole;
    }
}

function updateRoleBadge(role) {
    const badge = document.getElementById('roleBadge');
    const roleText = document.getElementById('userRole');
    const roleNames = {
        'security_engineer': 'Kỹ sư Bảo mật',
        'devops_engineer': 'Kỹ sư DevOps',
        'backend_developer': 'Lập trình viên Backend',
        'frontend_developer': 'Lập trình viên Frontend',
        'data_scientist': 'Nhà Khoa học Dữ liệu',
        'cloud_engineer': 'Kỹ sư Đám mây',
        'qa_engineer': 'Kỹ sư QA',
        'product_manager': 'Quản lý Sản phẩm'
    };
    const text = roleNames[role] || role;
    if (roleText) {
        roleText.textContent = text;
    } else if (badge) {
        badge.textContent = text;
    }
}

// Chat Functions
async function sendMessage() {
    const input = document.getElementById('chatInput');
    if (!input) return;
    const message = input.value.trim();

    if (!message) return;

    // Display user message
    displayMessage(message, 'user');
    input.value = '';

    // Show typing indicator
    const typingId = showTypingIndicator();

    try {
        const payload = {
            message,
            user_id: currentUser
        };

        if (activeSessionId) {
            payload.session_id = activeSessionId;
        }

        if (chatHistory.length > 0) {
            payload.chat_history = chatHistory.map(entry => [entry.user, entry.ai]);
        }

        if (selectedDocuments.length > 0) {
            payload.selected_documents = selectedDocuments.map(doc => ({
                type: doc.type,
                id: doc.id,
                filename: doc.filename
            }));
        }

        const response = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        removeTypingIndicator(typingId);

        const data = await response.json().catch(() => null);

        if (response.ok && data?.success !== false) {
            if (data?.session_id) {
                activeSessionId = data.session_id;
                localStorage.setItem('chat_session_id', activeSessionId);
            }

            displayMessage(data?.response || 'Không có phản hồi.', 'ai', data?.sources);
            chatHistory.push({
                user: message,
                ai: data?.response || '',
                sources: data?.sources || []
            });
        } else {
            const errorMessage = data?.error || 'Xin lỗi, đã xảy ra lỗi khi xử lý yêu cầu của bạn.';
            displayMessage(errorMessage, 'ai');
        }
    } catch (error) {
        removeTypingIndicator(typingId);
        console.error('Chat error:', error);
        displayMessage('Xin lỗi, không thể kết nối đến máy chủ.', 'ai');
    }
}

async function loadChatHistory(limit = 20) {
    const container = document.getElementById('chatMessages');
    if (!container) return;

    try {
        const response = await fetch(`${API_URL}/chat/history?limit=${limit}`, {
            credentials: 'include'
        });

        if (response.status === 401) {
            return;
        }

        if (!response.ok) {
            throw new Error('Failed to load chat history');
        }

        const data = await response.json();
        const history = Array.isArray(data.history) ? data.history : [];

        if (!history.length) {
            // If no history, show welcome summary
            await loadWelcomeSummary();
            return;
        }

        const orderedHistory = history.slice().reverse();
        container.innerHTML = '';
        chatHistory = [];

        orderedHistory.forEach(entry => {
            displayMessage(entry.question, 'user');
            displayMessage(entry.answer, 'ai', entry.sources);
            chatHistory.push({
                user: entry.question,
                ai: entry.answer,
                sources: entry.sources || []
            });
        });
        
        // Also load welcome summary below history
        await loadWelcomeSummary();
        
    } catch (error) {
        console.error('Error loading chat history:', error);
    }
}

async function loadWelcomeSummary() {
    /**
     * Load and display AI-generated welcome summary with:
     * - Hot news highlights with clickable links
     * - New documents with clickable links and descriptions
     * - Notable events
     * - System updates
     */
    try {
        const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[char]));

        const response = await fetch(`${API_URL}/chat/welcome-summary`, {
            credentials: 'include'
        });

        if (!response.ok) {
            console.warn('Could not load welcome summary');
            return;
        }

        const data = await response.json();
        if (data.success && data.summary) {
            const formattedSummary = formatSummaryText(data.summary);
            // Build HTML for hot news - always scroll to article in sidebar
            let hotNewsHtml = '';
            if (data.hot_news && data.hot_news.length > 0) {
                hotNewsHtml = '<div class="summary-section"><strong>🔥 Tin nổi bật:</strong><ul class="summary-links">';
                data.hot_news.forEach(news => {
                    // Always scroll to article in tech news section, don't open external link
                    const safeTitle = escapeHtml(news.title);
                    const safeSummary = escapeHtml(news.summary || news.description || '');
                    const linkHtml = `<a href="#" onclick="scrollToTechNews(${news.id}); return false;" class="summary-link">${safeTitle}</a>`;
                    hotNewsHtml += `<li>${linkHtml} <span class="views-badge">(${news.views} views)</span>`;
                    if (safeSummary) {
                        hotNewsHtml += `<br><small class="doc-description">${safeSummary}</small>`;
                    }
                    hotNewsHtml += `</li>`;
                });
                hotNewsHtml += '</ul></div>';
            }

            // Build HTML for new documents
            let newDocsHtml = '';
            if (data.new_docs && data.new_docs.length > 0) {
                newDocsHtml = '<div class="summary-section"><strong>📄 Tài liệu mới:</strong><ul class="summary-links">';
                data.new_docs.forEach(doc => {
                    // Clean the filename for display
                    const cleanName = formatDocumentName(doc.filename, 'Tài liệu');
                    const usageCount = Number(doc.usage_count ?? doc.interaction_count ?? 0) || 0;
                    newDocsHtml += `<li>`;
                    newDocsHtml += `<a href="#" onclick="scrollToDocument(${doc.id}); return false;" class="summary-link">${cleanName}</a>`;
                    newDocsHtml += `<span class="upload-date"> - ${doc.upload_date || ''}</span>`;
                    newDocsHtml += ` <span class="views-badge">(${usageCount} lượt tương tác)</span>`;
                    if (doc.description) {
                        newDocsHtml += `<br><small class="doc-description">${escapeHtml(doc.description)}</small>`;
                    }
                    newDocsHtml += `</li>`;
                });
                newDocsHtml += '</ul></div>';
            }

            // Display as a special system message
            const container = document.getElementById('chatMessages');
            if (!container) return;

            const welcomeDiv = document.createElement('div');
            welcomeDiv.className = 'message-wrapper system-message';
            welcomeDiv.innerHTML = `<div class="system-avatar"><i class="fas fa-sparkles"></i></div><div class="message-content system-content"><div class="system-header"><strong>Tóm tắt Hệ thống</strong></div><div class="system-body"><p>${formattedSummary}</p>${hotNewsHtml}${newDocsHtml}</div><div class="system-stats"><span><i class="fas fa-fire"></i> ${data.stats.hot_news_count} tin nổi bật</span><span><i class="fas fa-file-alt"></i> ${data.stats.new_docs_count} tài liệu mới</span>${data.stats.pending_uploads > 0 ? `<span><i class="fas fa-clock"></i> ${data.stats.pending_uploads} đang chờ</span>` : ''}</div></div>`;
            
            container.appendChild(welcomeDiv);
            container.scrollTop = container.scrollHeight;
        }
    } catch (error) {
        console.error('Error loading welcome summary:', error);
    }
}

function formatSummaryText(summaryText) {
    if (!summaryText || typeof summaryText !== 'string') {
        return '';
    }

    return summaryText
        .split('\n')
        .map(line => line.trim())
        .filter(line => line.length > 0)
        .join('<br>');
}

// Helper function to scroll to a tech news article
function scrollToTechNews(articleId) {
    // Switch to tech news tab
    const techNewsBtn = document.querySelector('[data-section="techNews"]');
    if (techNewsBtn) {
        techNewsBtn.click();
    }
    
    // Wait for content to load, then scroll to article
    setTimeout(() => {
        const articleElement = document.getElementById(`article-${articleId}`);
        if (articleElement) {
            articleElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
            articleElement.classList.add('highlight-flash');
            setTimeout(() => articleElement.classList.remove('highlight-flash'), 2000);
        }
    }, 300);
}

// Helper function to scroll to a document
async function scrollToDocument(docId) {
    // Switch to documents tab
    const docsBtn = document.querySelector('[data-section="documents"]');
    if (docsBtn) {
        docsBtn.click();
    }
    
    // Wait for tab to load
    await new Promise(resolve => setTimeout(resolve, 500));

    // First check if document is visible at current view
    let docElement = document.getElementById(`document-${docId}`);
    if (docElement) {
        docElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
        docElement.classList.add('highlight-flash');
        setTimeout(() => docElement.classList.remove('highlight-flash'), 2000);
        return;
    }

    // Document not found in current view - need to search for it
    // Fetch document info to find which folder it's in
    try {
        const response = await fetch(`${API_URL}/documents/${docId}`);
        if (response.ok) {
            const data = await response.json();
            if (data.success && data.document) {
                const doc = data.document;
                const folder = doc.folder || 'Chung';
                // Documents from /api/documents are company documents
                const docType = 'company';

                // Switch to company documents tab first
                const companyTab = document.querySelector('[data-doc-type="company"]');
                if (companyTab) {
                    companyTab.click();
                    await new Promise(resolve => setTimeout(resolve, 300));
                }

                // Load the folder containing the document
                await loadDocumentsInFolder(folder, docType);
                await new Promise(resolve => setTimeout(resolve, 500));

                // Try to find the document again
                docElement = document.getElementById(`document-${docId}`);
                if (docElement) {
                    docElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    docElement.classList.add('highlight-flash');
                    setTimeout(() => docElement.classList.remove('highlight-flash'), 2000);
                }
            }
        }
    } catch (error) {
        console.error('Error finding document:', error);
    }
}

// Expose helpers for inline onclick handlers (summary message links)
window.scrollToTechNews = scrollToTechNews;
window.scrollToDocument = scrollToDocument;

// Expose functions used by inline onclick handlers in pinned-doc menus
window.toggleDocumentSelection = toggleDocumentSelection;
window.downloadDocument = downloadDocument;
window.unpinDocument = unpinDocument;
window.closeAllKebabMenus = closeAllKebabMenus;

function displayMessage(text, sender, sources = null) {
    const messagesContainer = document.getElementById('chatMessages');
    if (!messagesContainer) return;
    const messageDiv = document.createElement('div');
    messageDiv.className = sender === 'user' ? 'user-message' : 'ai-message';

    const avatar = document.createElement('div');
    avatar.className = sender === 'user' ? 'user-avatar' : 'ai-avatar';
    const avatarIcon = sender === 'user' ? 'fa-user' : 'fa-robot';
    avatar.innerHTML = `<i class="fas ${avatarIcon}"></i>`;

    const content = document.createElement('div');
    content.className = 'message-content';

    // Format message with markdown-like syntax
    const formattedText = text
        // Headers (must be at start of line)
        .replace(/^### (.*?)$/gm, '<h4>$1</h4>')
        .replace(/^## (.*?)$/gm, '<h3>$1</h3>')
        .replace(/^# (.*?)$/gm, '<h2>$1</h2>')
        // Bold text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        // Italic text
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        // Inline code
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        // Bullet points
        .replace(/^- (.*?)$/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')
        // Numbered lists
        .replace(/^\d+\. (.*?)$/gm, '<li>$1</li>')
        // Newlines (but not after block elements)
        .replace(/\n(?!<)/g, '<br>');

    content.innerHTML = formattedText;

    // Add sources if available
    if (sources && sources.length > 0) {
        const sourcesDiv = document.createElement('div');
        sourcesDiv.className = 'message-sources';
        sourcesDiv.innerHTML = '<strong>📚 Nguồn:</strong><br>';
        sources.slice(0, 3).forEach((source, index) => {
            let label = source;
            if (typeof source === 'object' && source !== null) {
                const parts = [];
                if (source.filename) {
                    // Clean up the filename
                    let cleanFilename = source.filename;
                    // Remove common prefixes and clean up
                    cleanFilename = cleanFilename.replace(/^(The\s+)?Hacker\s+News\s+article\s*•?\s*/i, 'The Hacker News: ');
                    cleanFilename = cleanFilename.replace(/\s*•\s*trang\s+/i, ' • ');
                    parts.push(cleanFilename);
                }
                // Only show page number for documents (not articles)
                if (source.page && !source.filename?.toLowerCase().includes('article')) {
                    parts.push(`trang ${source.page}`);
                }
                label = parts.join(' • ') || source.filename || 'Tài liệu tham khảo';
            }
            sourcesDiv.innerHTML += `<div class="source-item">${index + 1}. ${label}</div>`;
        });
        content.appendChild(sourcesDiv);
    }

    // Add report button for AI messages
    if (sender === 'ai') {
        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'message-actions';
        
        const reportBtn = document.createElement('button');
        reportBtn.className = 'message-report-btn';
        reportBtn.innerHTML = '<i class="fas fa-flag"></i> Báo cáo';
        reportBtn.title = 'Báo cáo vấn đề với câu trả lời này';
        reportBtn.onclick = function() {
            // Get the previous user message for context
            const allMessages = messagesContainer.querySelectorAll('.user-message, .ai-message');
            let userQuestion = '';
            for (let i = allMessages.length - 1; i >= 0; i--) {
                if (allMessages[i] === messageDiv && i > 0) {
                    const prevMsg = allMessages[i - 1];
                    if (prevMsg.classList.contains('user-message')) {
                        userQuestion = prevMsg.querySelector('.message-content')?.textContent || '';
                    }
                    break;
                }
            }
            openReportModalWithContext(userQuestion, text);
        };
        
        actionsDiv.appendChild(reportBtn);
        content.appendChild(actionsDiv);
    }

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);
    messagesContainer.appendChild(messageDiv);

    // Scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function showTypingIndicator() {
    const messagesContainer = document.getElementById('chatMessages');
    if (!messagesContainer) return null;
    const typingDiv = document.createElement('div');
    typingDiv.className = 'ai-message typing-indicator';
    typingDiv.id = 'typing-' + Date.now();
    typingDiv.innerHTML = `
        <div class="ai-avatar"><i class="fas fa-robot"></i></div>
        <div class="message-content typing-bubble">
            <div class="typing-dots">
                <span></span>
                <span></span>
                <span></span>
            </div>
        </div>
    `;
    messagesContainer.appendChild(typingDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return typingDiv.id;
}

function removeTypingIndicator(id) {
    if (!id) return;
    const indicator = document.getElementById(id);
    if (indicator) indicator.remove();
}

// Download document helper
async function downloadDocument(type, id, filename) {
    try {
        const docId = id || filename;
        if (!docId) {
            alert('Không thể tải về: thiếu ID tài liệu');
            return;
        }

        // Open download in new tab/trigger download
        const downloadUrl = `${API_URL}/download/${docId}`;
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.target = '_blank';
        link.download = '';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    } catch (error) {
        console.error('Download error:', error);
        alert('Tải tài liệu thất bại');
    }
}

function clearChat() {
    if (confirm('Bạn có chắc chắn muốn xóa lịch sử trò chuyện?')) {
        const chatContainer = document.getElementById('chatMessages');
        if (!chatContainer) return;
        chatContainer.innerHTML = `<div class="welcome-message"><div class="ai-avatar"><i class="fas fa-robot"></i></div><div class="message-content"><p> Xin chào! Tôi là trợ lý AI của bạn. Hỏi tôi về:</p><ul><li> Tài liệu công ty nội bộ</li><li> Tin tức kỹ thuật mới nhất cho vai trò của bạn</li><li> Kiến thức cá nhân</li></ul></div></div>`;
        chatHistory = [];

        if (activeSessionId) {
            fetch(`${API_URL}/chat/clear`, {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ session_id: activeSessionId })
            }).catch(() => { });
        }

        activeSessionId = null;
        localStorage.removeItem('chat_session_id');
    }
}

// News Functions
function setNewsStatus(message, state = 'idle') {
    const statusEl = document.getElementById('newsStatus');
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.dataset.state = state;
}

function renderNewsFallback(message, actions = []) {
    const newsContainer = document.getElementById('newsFeed');
    if (!newsContainer) return;

    newsContainer.innerHTML = '';
    const wrapper = document.createElement('div');
    wrapper.className = 'news-empty-state';

    const text = document.createElement('p');
    text.textContent = message;
    wrapper.appendChild(text);

    if (Array.isArray(actions) && actions.length > 0) {
        const actionRow = document.createElement('div');
        actionRow.className = 'news-empty-actions';

        actions.forEach(action => {
            if (!action || typeof action.onClick !== 'function') {
                return;
            }
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'retry-btn';
            button.textContent = action.label || 'Try again';
            button.addEventListener('click', action.onClick);
            actionRow.appendChild(button);
        });

        if (actionRow.children.length > 0) {
            wrapper.appendChild(actionRow);
        }
    }

    newsContainer.appendChild(wrapper);
}

function renderNewsFromCache() {
    if (!newsCache.articles.length) {
        return false;
    }
    displayNews(newsCache.articles);
    setNewsStatus('Filtered results', 'idle');
    return true;
}

async function loadNews(options = {}) {
    console.log('>>> loadNews() called with options:', options);
    console.log('>>> currentRole is:', currentRole);

    const { force = false, silent = false } = options;
    const newsContainer = document.getElementById('newsFeed');
    if (!newsContainer) {
        console.warn('newsFeed container not found');
        return;
    }

    // Use default role if not set
    if (!currentRole) {
        console.log('>>> currentRole was empty, setting to security_engineer');
        currentRole = 'security_engineer';
    }

    const currentSort = document.getElementById('newsSortFilter')?.value || 'date';
    const cacheIsFresh = !force &&
        newsCache.role === currentRole &&
        newsCache.sortBy === currentSort &&
        newsCache.articles.length > 0 &&
        (Date.now() - newsCache.fetchedAt) < 60_000;

    if (cacheIsFresh) {
        displayNews(newsCache.articles);
        if (!silent) {
            setNewsStatus('Cached', 'idle');
        }
        return;
    }

    if (!silent) {
        newsContainer.innerHTML = '<div class="loading">Đang tải tin tức...</div>';
    }
    setNewsStatus('Đang làm mới…', 'busy');

    if (newsRequestController) {
        newsRequestController.abort();
    }
    newsRequestController = new AbortController();

    try {
        const sortBy = document.getElementById('newsSortFilter')?.value || 'date';
        const url = `${API_URL}/news/${currentRole}?limit=20&sort=${sortBy}`;
        console.log('Fetching news from:', url);

        const response = await fetch(url, {
            credentials: 'include',
            signal: newsRequestController.signal
        });

        console.log('News response status:', response.status);

        if (response.status === 404) {
            // No news for this role yet
            renderNewsFallback('No news available for your role yet.', [
                { label: 'Fetch Latest', onClick: () => fetchLatestNews({ reload: true }) }
            ]);
            setNewsStatus('Empty', 'idle');
            return;
        }

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        console.log('News data received:', data);

        newsCache = {
            role: currentRole,
            sortBy: sortBy,
            articles: data.articles || [],
            fetchedAt: Date.now()
        };
        if (!newsCache.articles.length) {
            renderNewsFallback('No news available yet.', [
                { label: 'Fetch Latest', onClick: () => fetchLatestNews({ reload: true }) }
            ]);
            setNewsStatus('Empty', 'idle');
        } else {
            displayNews(newsCache.articles);
            setNewsStatus('Updated', 'success');
        }
    } catch (error) {
        if (error.name === 'AbortError') {
            return;
        }
        console.error('Error loading news:', error);
        if (!silent) {
            renderNewsFallback('Unable to load news - check if server is running', [
                { label: 'Retry', onClick: () => loadNews({ force: true }) }
            ]);
        }
        setNewsStatus('Failed', 'error');
    } finally {
        newsRequestController = null;
    }
}

function displayNews(articles) {
    const newsContainer = document.getElementById('newsFeed');
    if (!newsContainer) return;

    const filteredArticles = filterArticlesByTime(articles);
    const list = filteredArticles || [];

    if (!list || list.length === 0) {
        const currentFilter = document.getElementById('newsTimeFilter')?.value || 'all';
        if (articles && articles.length > 0 && currentFilter !== 'all') {
            renderNewsFallback('No articles match this time filter yet.', [
                {
                    label: 'Show all news',
                    onClick: () => {
                        const filterSelect = document.getElementById('newsTimeFilter');
                        if (filterSelect) {
                            filterSelect.value = 'all';
                        }
                        displayNews(articles);
                    }
                },
                { label: 'Fetch latest news', onClick: () => fetchLatestNews({ reload: true }) }
            ]);
        } else {
            renderNewsFallback('No news available for your role yet.', [
                { label: 'Fetch latest news', onClick: () => fetchLatestNews({ reload: true }) }
            ]);
        }
        return;
    }

    newsContainer.innerHTML = '';

    list.forEach(article => {
        const card = createNewsCard(article);
        newsContainer.appendChild(card);
    });
}

function filterArticlesByTime(articles) {
    const filter = document.getElementById('newsTimeFilter')?.value || 'all';
    if (filter === 'all') return articles;

    const now = new Date();
    return articles.filter(article => {
        if (!article.published_date) return false;
        const published = new Date(article.published_date);
        const diffHours = (now - published) / 3600000;
        if (filter === 'today') {
            return diffHours <= 24;
        }
        if (filter === 'week') {
            return diffHours <= 24 * 7;
        }
        return true;
    });
}

function createNewsCard(article) {
    const card = document.createElement('div');
    card.className = 'news-card';
    card.id = `article-${article.id}`;

    const titleText = article.title || 'Untitled';

    if (titleText && (titleText.toLowerCase().includes('cve') ||
        titleText.toLowerCase().includes('vulnerability') ||
        titleText.toLowerCase().includes('critical'))) {
        card.classList.add('critical');
    }

    const title = document.createElement('h4');
    title.className = 'news-title';
    title.textContent = titleText;
    title.style.cursor = 'pointer';
    title.onclick = () => {
        const articleUrl = getArticleUrl(article);
        if (articleUrl) {
            const newWindow = window.open(articleUrl, '_blank');
            if (newWindow) {
                newWindow.opener = null;
            }
            // Increment view count when user reads article
            incrementArticleView(article.id);
        } else {
            alert('Không có liên kết bài viết cho mục này.');
        }
    };

    const summary = document.createElement('div');
    summary.className = 'news-summary';
    summary.textContent = buildArticleSnippet(article);

    const meta = document.createElement('div');
    meta.className = 'news-meta';

    const source = document.createElement('div');
    source.className = 'news-source';
    source.innerHTML = `<i class="fas fa-rss"></i> ${resolveArticleSource(article)}`;

    const date = document.createElement('div');
    date.className = 'news-date';
    date.innerHTML = `<i class="far fa-clock"></i> ${formatDate(article.published_date)}`;

    const viewCount = document.createElement('div');
    viewCount.className = 'news-views';
    const internalViews = article.view_count || 0;
    const onlineViews = article.online_view_count || 0;
    const totalViews = article.total_views || (internalViews + onlineViews);
    viewCount.innerHTML = `<i class="fas fa-eye"></i> ${totalViews} lượt xem`;
    viewCount.title = `Nội bộ: ${internalViews}, Trực tuyến: ${onlineViews}`;

    meta.appendChild(source);
    meta.appendChild(date);
    meta.appendChild(viewCount);

    const actions = document.createElement('div');
    actions.className = 'news-actions';

    const explainBtn = document.createElement('button');
    explainBtn.className = 'btn-news-action';
    explainBtn.innerHTML = `<i class="fas fa-book"></i> Giải thích Thuật ngữ`;
    explainBtn.onclick = () => explainArticleTerms(article, explainBtn);

    const summarizeBtn = document.createElement('button');
    summarizeBtn.className = 'btn-news-action';
    summarizeBtn.innerHTML = `<i class="fas fa-compress"></i> Tóm tắt Bài viết`;
    summarizeBtn.onclick = () => summarizeNewsArticle(article, summarizeBtn);

    actions.appendChild(explainBtn);
    actions.appendChild(summarizeBtn);

    card.appendChild(title);
    card.appendChild(summary);
    card.appendChild(meta);
    card.appendChild(actions);

    return card;
}

function resolveArticleSource(article) {
    return article.source_name || article.source || article.publisher || 'Tech News';
}

function getArticleUrl(article) {
    return article.link || article.url || article.article_url || null;
}

function buildArticleSnippet(article) {
    if (article.summary) return article.summary;
    if (article.content_snippet) return article.content_snippet;
    const content = article.content || '';
    if (!content.trim()) return 'No summary available';
    return content.trim().split(/\s+/).slice(0, 40).join(' ') + '...';
}

async function summarizeNewsArticle(article, buttonEl) {
    if (!article?.id) {
        alert('Bài viết này thiếu mã định danh. Vui lòng làm mới tin tức.');
        return;
    }

    const questionText = `Tóm tắt bài viết này: "${article.title || 'bài viết này'}"`;

    displayMessage(questionText, 'user');
    const typingId = showTypingIndicator();

    if (buttonEl) {
        buttonEl.disabled = true;
        buttonEl.textContent = '⏳ Đang xử lý...';
    }

    try {
        const response = await fetch(`${API_URL}/news/summarize/${article.id}`, {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: activeSessionId,
                question: questionText
            })
        });

        const data = await response.json().catch(() => null);
        removeTypingIndicator(typingId);

        if (!response.ok || !data?.success) {
            throw new Error(data?.error || 'Unable to summarize this article.');
        }

        if (data.session_id) {
            activeSessionId = data.session_id;
            localStorage.setItem('chat_session_id', activeSessionId);
        }

        displayMessage(data.summary, 'ai', data.sources);
        chatHistory.push({
            user: questionText,
            ai: data.summary,
            sources: data.sources || []
        });
    } catch (error) {
        console.error('Summarize article error:', error);
        removeTypingIndicator(typingId);
        displayMessage(error.message || 'Không thể tóm tắt bài viết này ngay bây giờ.', 'ai');
        alert(error.message || 'Không thể tóm tắt bài viết này ngay bây giờ.');
    } finally {
        if (buttonEl) {
            buttonEl.disabled = false;
            buttonEl.innerHTML = `<i class="fas fa-compress"></i> Tóm tắt Bài viết`;
        }
    }
}

async function explainArticleTerms(article, buttonEl = null) {
    if (!article || !article.id) {
        alert('Bài viết này thiếu mã định danh.');
        return;
    }

    const questionText = `Giải thích các thuật ngữ kỹ thuật trong bài viết: "${article.title || 'bài viết này'}"`;


    displayMessage(questionText, 'user');
    const typingId = showTypingIndicator();

    if (buttonEl) {
        buttonEl.disabled = true;
        buttonEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Đang xử lý...';
    }

    try {
        const response = await fetch(`${API_URL}/news/explain/${article.id}`, {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: activeSessionId,
                question: questionText
            })
        });

        console.log('[DEBUG] Explain response status:', response.status);

        removeTypingIndicator(typingId);

        if (!response.ok) {
            const errorText = await response.text().catch(() => response.statusText);
            console.error('[DEBUG] Explain error:', errorText);
            throw new Error(errorText || 'Failed to explain terms');
        }

        const data = await response.json();
        console.log('[DEBUG] Explain result:', data);

        if (data.session_id) {
            activeSessionId = data.session_id;
            localStorage.setItem('chat_session_id', activeSessionId);
        }

        displayMessage(data.explanation || 'No explanation available.', 'ai', data.sources);

        chatHistory.push({
            user: questionText,
            ai: data.explanation,
            sources: data.sources || []
        });
    } catch (error) {
        console.error('Explain article error:', error);
        removeTypingIndicator(typingId);
        displayMessage(error.message || 'Không thể giải thích thuật ngữ bài viết ngay bây giờ.', 'ai');
        alert(error.message || 'Không thể giải thích thuật ngữ bài viết ngay bây giờ.');
    } finally {
        if (buttonEl) {
            buttonEl.disabled = false;
            buttonEl.innerHTML = `<i class="fas fa-book"></i> Giải thích Thuật ngữ`;
        }
    }
}

async function incrementArticleView(articleId) {
    if (!articleId) return;

    try {
        await fetch(`${API_URL}/news/view/${articleId}`, {
            method: 'POST',
            credentials: 'include'
        });
    } catch (error) {
        console.error('Failed to increment view count:', error);
    }
}

async function refreshNews() {
    const btn = document.getElementById('refreshNews');
    if (btn) {
        btn.classList.add('spinning');
        btn.disabled = true;
    }
    setNewsStatus('Refreshing…', 'busy');

    try {
        await loadNews({ force: true });
    } catch (error) {
        console.error('Error refreshing news:', error);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('spinning');
        }
    }
}

async function fetchLatestNews(options = {}) {
    const { silent = false, reload = false } = options;

    if (!currentRole || latestNewsFetchInFlight) {
        if (!currentRole) {
            console.warn('Cannot fetch latest news before role is set');
        }
        return;
    }

    latestNewsFetchInFlight = true;
    const btn = document.getElementById('fetchLatestNews');
    const label = btn?.querySelector('span');
    const originalLabel = label?.textContent;

    if (btn) {
        btn.disabled = true;
        btn.classList.add('active');
    }
    if (label) {
        label.textContent = 'Đang tải…';
    }
    setNewsStatus('Đang tìm bài viết mới nhất…', 'busy');

    try {
        console.log('[DEBUG] Fetching news for role:', currentRole);
        const response = await fetch(`${API_URL}/news/fetch`, {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                role: currentRole
            })
        });

        console.log('[DEBUG] Fetch response status:', response.status);
        
        if (!response.ok) {
            const errorText = await response.text().catch(() => response.statusText);
            console.error('[DEBUG] Fetch error response:', errorText);
            throw new Error(errorText || 'Failed to fetch latest news');
        }

        const result = await response.json().catch(() => ({}));
        console.log('[DEBUG] Fetch success result:', result);
        
        setNewsStatus('New sources ingested', 'success');
        if (reload) {
            await loadNews({ force: true });
        }
        if (!silent) {
            console.info('News feed refreshed from sources');
        }
    } catch (error) {
        console.error('[DEBUG] Error fetching news:', error);
        console.error('[DEBUG] Error message:', error.message);
        console.error('[DEBUG] Error stack:', error.stack);
        setNewsStatus('Tải thất bại', 'error');
        if (!silent) {
            alert(`Không thể tải tin tức: ${error.message}\n\nKiểm tra bảng điều khiển trình duyệt (F12) để biết chi tiết.`);
        }
    } finally {
        latestNewsFetchInFlight = false;
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('active');
        }
        if (label && originalLabel) {
            label.textContent = originalLabel;
        }
    }
}

function formatDocumentName(name, fallback = 'Untitled document') {
    if (!name || typeof name !== 'string') {
        return fallback;
    }

    let cleaned = name.trim();
    // Remove UUID-style prefixes saved during upload
    cleaned = cleaned.replace(/^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}_/, '');
    cleaned = cleaned.replace(/^[0-9a-fA-F]{32}_/, '');
    // Remove common label prefixes like TEAM - , PERSONAL - , COMPANY -
    cleaned = cleaned.replace(/^(team|personal|company)\s*[-_]\s*/i, '');
    cleaned = cleaned.replace(/^(doc|file)\s*[-_]\s*/i, '');
    cleaned = cleaned.replace(/\s+/g, ' ').trim();

    return cleaned || fallback;
}

function createDocumentListItem({ type, id, filename, displayName, metaText, description, onClick }) {
    const item = document.createElement('div');
    const key = buildDocKey(type, id, filename);
    item.className = 'document-item';
    item.id = `document-${id}`;
    item.dataset.docKey = key;
    item.dataset.docType = type;
    item.dataset.docId = id ?? '';
    item.dataset.docFilename = filename ?? '';

    // Title (name only)
    const title = document.createElement('div');
    title.className = 'document-title';
    title.textContent = displayName;
    item.appendChild(title);

    // Always show description as tooltip (hover) rather than inline text
    const tooltip = String(description ?? '').trim();
    if (tooltip) {
        title.title = tooltip;
        item.title = tooltip;
    }

    // Kebab menu (3-dot menu)
    const menuWrapper = document.createElement('div');
    menuWrapper.className = 'kebab-menu-wrapper';

    const menuBtn = document.createElement('button');
    menuBtn.type = 'button';
    menuBtn.className = 'kebab-menu-btn';
    menuBtn.innerHTML = '<i class="fas fa-ellipsis-v"></i>';
    menuBtn.title = 'Tùy chọn';
    menuBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        closeAllKebabMenus();
        // Position dropdown using fixed positioning
        const rect = menuBtn.getBoundingClientRect();
        menuDropdown.style.top = `${rect.bottom + 4}px`;
        menuDropdown.style.left = `${Math.max(10, rect.right - 160)}px`;
        menuDropdown.classList.toggle('show');
    });

    const menuDropdown = document.createElement('div');
    menuDropdown.className = 'kebab-menu-dropdown';

    // Menu items
    const menuItems = [];

    // Use/Select option
    const useItem = document.createElement('div');
    useItem.className = 'kebab-menu-item';
    useItem.innerHTML = '<i class="fas fa-comment-dots"></i> Dùng để hỏi';
    useItem.addEventListener('click', (event) => {
        event.stopPropagation();
        const nowSelected = toggleDocumentSelection({ type, id, filename, label: displayName });
        useItem.innerHTML = nowSelected
            ? '<i class="fas fa-check"></i> Đã chọn'
            : '<i class="fas fa-comment-dots"></i> Dùng để hỏi';
        menuDropdown.classList.remove('show');
    });
    menuItems.push(useItem);

    // Pin/Unpin option
    const pinItem = document.createElement('div');
    pinItem.className = 'kebab-menu-item pin-menu-item';
    pinItem.innerHTML = '<i class="fas fa-thumbtack"></i> Ghim';
    pinItem.addEventListener('click', async (event) => {
        event.stopPropagation();
        const isPinned = pinItem.classList.contains('pinned');
        if (isPinned) {
            await unpinDocument(id, type);
            pinItem.classList.remove('pinned');
            pinItem.innerHTML = '<i class="fas fa-thumbtack"></i> Ghim';
        } else {
            await pinDocument(id, type);
            pinItem.classList.add('pinned');
            pinItem.innerHTML = '<i class="fas fa-thumbtack"></i> Bỏ ghim';
        }
        menuDropdown.classList.remove('show');
    });
    // Check if already pinned
    checkPinStatus(id, type).then(isPinned => {
        if (isPinned) {
            pinItem.classList.add('pinned');
            pinItem.innerHTML = '<i class="fas fa-thumbtack"></i> Bỏ ghim';
        }
    });
    menuItems.push(pinItem);

    // Download option
    const downloadItem = document.createElement('div');
    downloadItem.className = 'kebab-menu-item';
    downloadItem.innerHTML = '<i class="fas fa-download"></i> Tải về';
    downloadItem.addEventListener('click', (event) => {
        event.stopPropagation();
        downloadDocument(type, id, filename);
        menuDropdown.classList.remove('show');
    });
    menuItems.push(downloadItem);

    // Rename option (for personal documents only)
    if (type === 'personal') {
        const renameItem = document.createElement('div');
        renameItem.className = 'kebab-menu-item';
        renameItem.innerHTML = '<i class="fas fa-edit"></i> Đổi tên';
        renameItem.addEventListener('click', (event) => {
            event.stopPropagation();
            showRenamePersonalFileModal(id, displayName);
            menuDropdown.classList.remove('show');
        });
        menuItems.push(renameItem);
    }

    // Add all menu items to dropdown
    menuItems.forEach(menuItem => menuDropdown.appendChild(menuItem));

    menuWrapper.appendChild(menuBtn);
    menuWrapper.appendChild(menuDropdown);
    item.appendChild(menuWrapper);

    if (typeof onClick === 'function') {
        item.addEventListener('click', onClick);
    }

    const isSelected = selectedDocuments.some(doc => doc.key === key);
    if (isSelected) {
        item.classList.add('selected');
        useItem.innerHTML = '<i class="fas fa-check"></i> Đã chọn';
    }

    return item;
}

// Close all kebab menus when clicking outside
document.addEventListener('click', () => {
    closeAllKebabMenus();
});

function closeAllKebabMenus() {
    document.querySelectorAll('.kebab-menu-dropdown.show').forEach(menu => {
        menu.classList.remove('show');
    });
}

function renderListError(container, message, retryHandler) {
    if (!container) return;
    container.innerHTML = '';

    const wrapper = document.createElement('div');
    wrapper.className = 'list-error';

    const text = document.createElement('p');
    text.textContent = message;
    wrapper.appendChild(text);

    if (typeof retryHandler === 'function') {
        const retryBtn = document.createElement('button');
        retryBtn.type = 'button';
        retryBtn.className = 'retry-btn';
        retryBtn.innerHTML = '<i class="fas fa-redo"></i><span>Thử lại</span>';
        retryBtn.addEventListener('click', (event) => {
            event.preventDefault();
            retryHandler();
        });
        wrapper.appendChild(retryBtn);
    }

    container.appendChild(wrapper);
}

// Document Functions
async function loadPersonalDocuments() {
    console.log('>>> loadPersonalDocuments() called');
    console.log('>>> currentRole is:', currentRole);

    const container = document.getElementById('personalDocumentList');
    if (!container) {
        console.warn('personalDocumentList container not found');
        return;
    }

    // Use default role if not set
    if (!currentRole) {
        console.log('>>> currentRole was empty, setting to security_engineer');
        currentRole = 'security_engineer';
    }

    container.innerHTML = '<div class="loading">Đang tải thư mục...</div>';
    console.log('>>> About to fetch personal doc folders');

    try {
        const url = `${API_URL}/user-documents/folders`;
        console.log('>>> Fetching folders from:', url);

        const response = await fetch(url, {
            credentials: 'include'
        });

        console.log('Folders response status:', response.status);

        if (response.status === 404) {
            container.innerHTML = '<div style="text-align:center;color:#858796;font-size:12px;padding:20px;">Chưa có thư mục</div>';
            return;
        }

        if (response.status === 401) {
            renderListError(container, 'Please login to view documents.', () => window.location.href = '/login.html');
            return;
        }

        if (response.ok) {
            const data = await response.json();
            console.log('Folders data:', data);
            displayPersonalFolders(data.folders || []);
        } else {
            let errText = 'Failed to load folders';
            try {
                const json = await response.json();
                if (json && json.error) errText = json.error;
            } catch (e) { }
            console.warn('Personal folders load failed:', response.status, errText);
            renderListError(container, errText, loadPersonalDocuments);
        }
    } catch (error) {
        console.error('Error loading personal folders:', error);
        renderListError(container, 'Network error - check if server is running', loadPersonalDocuments);
    }
}

function displayPersonalFolders(folders) {
    const container = document.getElementById('personalDocumentList');
    if (!container) return;

    if (!folders || folders.length === 0) {
        container.innerHTML = '<div style="text-align:center;color:#858796;font-size:12px;padding:20px;">Không có thư mục</div>';
        return;
    }

    container.innerHTML = '<div class="folder-grid"></div>';
    const grid = container.querySelector('.folder-grid');

    folders.forEach(folder => {
        const folderCard = document.createElement('div');
        folderCard.className = 'folder-card personal-folder';

        const escapedName = folder.name.replace(/'/g, "\\'").replace(/"/g, '&quot;');

        folderCard.innerHTML = `
            <div class="folder-icon">
                <i class="fas fa-${folder.icon || 'folder'}"></i>
            </div>
            <div class="folder-name">${folder.name}</div>
            <div class="folder-count">${folder.count} tài liệu</div>
            <div class="kebab-menu-wrapper folder-kebab">
                <button type="button" class="kebab-menu-btn" title="Tùy chọn">
                    <i class="fas fa-ellipsis-v"></i>
                </button>
                <div class="kebab-menu-dropdown">
                    <div class="kebab-menu-item" onclick="event.stopPropagation(); showRenamePersonalFolderModal('${escapedName}'); closeAllKebabMenus();">
                        <i class="fas fa-edit"></i> Đổi tên
                    </div>
                    <div class="kebab-menu-item delete-item" onclick="event.stopPropagation(); deletePersonalFolder('${escapedName}'); closeAllKebabMenus();">
                        <i class="fas fa-trash"></i> Xóa
                    </div>
                </div>
            </div>
        `;

        // Add click handler for kebab button with fixed positioning
        // Move dropdown to body for proper z-index stacking
        const kebabBtn = folderCard.querySelector('.kebab-menu-btn');
        const dropdown = folderCard.querySelector('.kebab-menu-dropdown');

        // Remove dropdown from folder card and append to body
        dropdown.remove();
        dropdown.style.position = 'fixed';
        dropdown.style.zIndex = '99999';
        document.body.appendChild(dropdown);

        kebabBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            closeAllKebabMenus();
            const rect = kebabBtn.getBoundingClientRect();
            dropdown.style.top = `${rect.bottom + 4}px`;
            dropdown.style.left = `${Math.max(10, rect.right - 160)}px`;
            dropdown.classList.add('show');
        });

        folderCard.onclick = () => loadDocumentsInFolder(folder.name, 'personal');
        grid.appendChild(folderCard);
    });
}

function displayPersonalDocuments(documents) {
    const container = document.getElementById('personalDocumentList');
    if (!container) return;

    if (documents.length === 0) {
        container.innerHTML = '<div style="text-align:center;color:#858796;font-size:12px;padding:20px;">Chưa có tài liệu cá nhân</div>';
        return;
    }

    container.innerHTML = '';

    documents.forEach(doc => {
        const rawName = doc.original_filename || doc.filename || doc.file_name;
        const displayName = formatDocumentName(rawName, 'Untitled document');
        const filename = doc.filename || doc.file_name;

        const item = createDocumentListItem({
            type: 'personal',
            id: doc.id,
            filename,
            displayName,
            metaText: null,
            description: doc.description,
            onClick: () => {
                // Auto-select this document for the query
                const docInfo = { type: 'personal', id: doc.id, filename, label: displayName };
                // Make sure it's selected (not toggled off)
                if (!selectedDocuments.some(d => d.id === doc.id && d.type === 'personal')) {
                    toggleDocumentSelection(docInfo);
                }

                const chatInput = document.getElementById('chatInput');
                if (chatInput) {
                    chatInput.value = `Tài liệu ${displayName} nói về nội dung gì?`;
                    chatInput.focus();
                }
            }
        });

        container.appendChild(item);
    });

    syncDocumentSelectionStyles();
}

async function loadMyUploads() {
    const container = document.getElementById('uploadsList');
    if (!container) return;

    container.innerHTML = '<div class="loading">Đang tải...</div>';

    try {
        const response = await fetch(`${API_URL}/user-documents/my`, {
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            displayMyUploads(data.documents || []);
        } else {
            container.innerHTML = '<div class="loading">❌ Tải thất bại</div>';
        }
    } catch (error) {
        console.error('Error loading my uploads:', error);
        container.innerHTML = '<div class="loading">❌ Lỗi tải tài liệu</div>';
    }
}

async function loadCompanyDocuments() {
    const container = document.getElementById('documentList');
    if (!container) {
        console.warn('documentList container not found');
        return;
    }
    container.innerHTML = '<div class="loading">Đang tải thư mục...</div>';
    console.log('Loading company document folders...');

    try {
        const url = `${API_URL}/documents/folders`;
        console.log('Fetching:', url);

        const response = await fetch(url, {
            credentials: 'include'
        });

        console.log('Folders response status:', response.status);

        if (response.status === 401) {
            renderListError(container, 'Please login', () => window.location.href = '/login.html');
            return;
        }

        if (response.ok) {
            const data = await response.json();
            console.log('Folders data:', data);
            const folders = data.folders || [];
            displayCompanyFolders(folders);
        } else {
            let errText = 'Failed to load folders';
            try {
                const json = await response.json();
                if (json && json.error) errText = json.error;
            } catch (e) { }
            renderListError(container, errText, loadCompanyDocuments);
        }
    } catch (error) {
        console.error('Error loading company folders:', error);
        renderListError(container, 'Network error', loadCompanyDocuments);
    }
}

function displayCompanyFolders(folders) {
    const container = document.getElementById('documentList');
    if (!container) return;

    if (!folders || folders.length === 0) {
        container.innerHTML = '<div style="text-align:center;color:#858796;font-size:12px;padding:20px;">Không có thư mục</div>';
        return;
    }

    container.innerHTML = '<div class="folder-grid"></div>';
    const grid = container.querySelector('.folder-grid');

    folders.forEach(folder => {
        const folderCard = document.createElement('div');
        folderCard.className = 'folder-card';
        folderCard.innerHTML = `
            <div class="folder-icon">
                <i class="fas fa-${folder.icon || 'folder'}"></i>
            </div>
            <div class="folder-name">${folder.name}</div>
            <div class="folder-count">${folder.count} tài liệu</div>
        `;
        folderCard.onclick = () => loadDocumentsInFolder(folder.name, 'company');
        grid.appendChild(folderCard);
    });
}

async function loadDocumentsInFolder(folderName, docType) {
    // Get the entire tab content container
    const tabContent = document.getElementById('documents-tab');
    if (!tabContent) return;

    // Hide both document sections and show a folder view
    tabContent.innerHTML = `
        <div class="folder-view-container">
            <div class="folder-header">
                <button class="back-button" id="backToFoldersBtn">
                    <i class="fas fa-arrow-left"></i> Quay lại
                </button>
                <h4><i class="fas fa-folder-open"></i> ${folderName}</h4>
                <span class="folder-type-badge ${docType}">${docType === 'company' ? 'Công ty' : 'Cá nhân'}</span>
            </div>
            <div class="documents-in-folder" id="folderDocuments">
                <div class="loading">Đang tải tài liệu...</div>
            </div>
        </div>
    `;

    // Add click handler for back button
    document.getElementById('backToFoldersBtn').onclick = () => {
        // Restore original tab structure
        restoreDocumentsTabStructure();
        // Reload both document lists
        loadCompanyDocuments();
        loadPersonalDocuments();
    };

    try {
        const endpoint = docType === 'company' 
            ? `/documents/by-folder/${encodeURIComponent(folderName)}`
            : `/user-documents/by-folder/${encodeURIComponent(folderName)}`;
        
        const response = await fetch(`${API_URL}${endpoint}`, {
            credentials: 'include'
        });

        if (!response.ok) {
            throw new Error('Failed to load documents');
        }

        const data = await response.json();
        const documents = data.documents || [];
        
        displayDocumentsInFolder(documents, folderName, docType);
    } catch (error) {
        console.error('Error loading documents in folder:', error);
        const container = document.getElementById('folderDocuments');
        if (container) {
            container.innerHTML = `
                <div class="list-error">
                    <i class="fas fa-exclamation-circle"></i>
                    <span>Lỗi tải tài liệu</span>
                    <button onclick="loadDocumentsInFolder('${folderName.replace(/'/g, "\\'")}', '${docType}')">Thử lại</button>
                </div>
            `;
        }
    }
}

function restoreDocumentsTabStructure() {
    const tabContent = document.getElementById('documents-tab');
    if (!tabContent) return;

    tabContent.innerHTML = `
        <div class="document-section">
            <div class="section-heading">
                <h3><i class="fas fa-building"></i> Tài liệu Công ty</h3>
                <button class="section-refresh" data-target="company-docs" title="Tải lại tài liệu công ty">
                    <i class="fas fa-sync-alt"></i>
                </button>
            </div>
            <div class="document-list" id="documentList">
                <div class="loading">Đang tải...</div>
            </div>
        </div>
        <div class="document-section">
            <div class="section-heading">
                <h3><i class="fas fa-users"></i> Tài liệu Cá nhân</h3>
                <button class="section-refresh" data-target="personal-docs" title="Tải lại tài liệu cá nhân">
                    <i class="fas fa-sync-alt"></i>
                </button>
            </div>
            <div class="document-list" id="personalDocumentList">
                <div class="loading">Đang tải...</div>
            </div>
        </div>
    `;
    
    // Re-attach refresh button handlers
    document.querySelectorAll('.section-refresh').forEach(button => {
        button.addEventListener('click', async () => {
            const target = button.dataset.target;
            button.disabled = true;
            button.classList.add('spinning');
            try {
                if (target === 'personal-docs') {
                    await loadPersonalDocuments();
                } else {
                    await loadCompanyDocuments();
                }
            } finally {
                button.disabled = false;
                button.classList.remove('spinning');
            }
        });
    });
}

function displayDocumentsInFolder(documents, folderName, docType) {
    const container = document.getElementById('folderDocuments');
    if (!container) return;

    container.innerHTML = '';

    if (!documents || documents.length === 0) {
        container.innerHTML = '<div style="text-align:center;color:#858796;font-size:12px;padding:20px;">Không có tài liệu trong thư mục này</div>';
        return;
    }

    documents.forEach(doc => {
        const rawName = doc.original_filename || doc.filename || doc.file_name;
        const displayName = formatDocumentName(rawName, 'Untitled document');
        const filename = doc.filename || doc.file_name;
        
        // Parse metadata for description if available
        let description = doc.description || '';
        if (!description && doc.metadata) {
            try {
                const metadata = typeof doc.metadata === 'string' ? JSON.parse(doc.metadata) : doc.metadata;
                description = metadata.description || '';
            } catch(e) {}
        }

        const item = createDocumentListItem({
            type: docType,
            id: doc.id,
            filename,
            displayName,
            metaText: `🔥 ${doc.usage_count || 0} lượt sử dụng`,
            description: description,
            onClick: () => {
                // Auto-select this document for the query
                const docInfo = { type: docType, id: doc.id, filename, label: displayName };
                // Make sure it's selected (not toggled off)
                if (!selectedDocuments.some(d => d.id === doc.id && d.type === docType)) {
                    toggleDocumentSelection(docInfo);
                }

                const chatInput = document.getElementById('chatInput');
                if (chatInput) {
                    chatInput.value = `Tài liệu ${displayName} nói về nội dung gì?`;
                    chatInput.focus();
                }
            }
        });

        container.appendChild(item);
    });

    syncDocumentSelectionStyles();
}

function displayCompanyDocuments(documents) {
    const container = document.getElementById('documentList');
    if (!container) return;

    if (!documents || documents.length === 0) {
        container.innerHTML = '<div style="text-align:center;color:#858796;font-size:12px;padding:20px;">Không có tài liệu</div>';
        return;
    }

    container.innerHTML = '';

    documents.forEach(doc => {
        const rawName = doc.original_filename || doc.filename || doc.file_name;
        const displayName = formatDocumentName(rawName, 'Untitled document');
        const filename = doc.filename || doc.file_name;

        const item = createDocumentListItem({
            type: 'company',
            id: doc.id,
            filename,
            displayName,
            metaText: null,
            description: doc.description,
            onClick: () => {
                // Auto-select this document for the query
                const docInfo = { type: 'company', id: doc.id, filename, label: displayName };
                // Make sure it's selected (not toggled off)
                if (!selectedDocuments.some(d => d.id === doc.id && d.type === 'company')) {
                    toggleDocumentSelection(docInfo);
                }

                const chatInput = document.getElementById('chatInput');
                if (chatInput) {
                    chatInput.value = `Tài liệu ${displayName} nói về nội dung gì?`;
                    chatInput.focus();
                }
            }
        });

        container.appendChild(item);
    });

    syncDocumentSelectionStyles();
}

function displayMyUploads(documents) {
    const container = document.getElementById('uploadsList');
    if (!container) return;

    if (documents.length === 0) {
        container.innerHTML = '<div style="text-align:center;color:#858796;font-size:12px;padding:15px;">Chưa có tải lên</div>';
        return;
    }

    container.innerHTML = '';

    documents.forEach(doc => {
        const rawName = doc.original_filename || doc.filename || doc.file_name;
        const displayName = formatDocumentName(rawName, 'Untitled upload');
        const statusValue = (doc.status || 'pending').toLowerCase();
        const statusLabel = statusValue.charAt(0).toUpperCase() + statusValue.slice(1);
        const timestamp = doc.created_at || doc.uploaded_at || doc.approved_at;

        const item = document.createElement('div');
        item.className = 'upload-item';
        item.innerHTML = `
            <div>
                ${displayName}
                <span class="status ${statusValue}">${statusLabel}</span>
            </div>
            <div style="font-size:10px;color:#858796;margin-top:3px;">
                ${formatDate(timestamp)}
            </div>
        `;
        container.appendChild(item);
    });
}

// ==================== PINNED DOCUMENTS ====================

async function loadPinnedDocuments() {
    const container = document.getElementById('pinnedDocumentList');
    if (!container) {
        console.warn('pinnedDocumentList container not found');
        return;
    }

    container.innerHTML = '<div class="loading">Đang tải...</div>';
    console.log('Loading pinned documents...');

    try {
        const response = await fetch(`${API_URL}/pinned-documents`, {
            credentials: 'include'
        });

        if (response.status === 401) {
            renderListError(container, 'Please login to view pinned documents.', () => window.location.href = '/login.html');
            return;
        }

        if (response.ok) {
            const data = await response.json();
            console.log('Pinned documents data:', data);
            displayPinnedDocuments(data.documents || []);
        } else {
            let errText = 'Failed to load pinned documents';
            try {
                const json = await response.json();
                if (json && json.error) errText = json.error;
            } catch (e) { }
            console.warn('Pinned documents load failed:', response.status, errText);
            renderListError(container, errText, loadPinnedDocuments);
        }
    } catch (error) {
        console.error('Error loading pinned documents:', error);
        renderListError(container, 'Network error - check if server is running', loadPinnedDocuments);
    }
}

function displayPinnedDocuments(documents) {
    const container = document.getElementById('pinnedDocumentList');
    if (!container) return;

    if (!documents || documents.length === 0) {
        container.innerHTML = '<div style="text-align:center;color:#858796;font-size:12px;padding:20px;">Chưa có tài liệu được ghim<br><small>Ghim tài liệu từ tab Tài liệu để truy cập nhanh</small></div>';
        return;
    }

    container.innerHTML = '';

    documents.forEach(doc => {
        const displayName = formatDocumentName(doc.filename, 'Untitled document');
        const typeLabel = doc.document_type === 'company' ? '🏢 Công ty' : '👤 Cá nhân';
        const folderLabel = doc.folder ? `📁 ${doc.folder}` : '';
        const isAdminPinned = doc.admin_pinned === true;
        const adminLabel = isAdminPinned ? '<span class="admin-pinned-badge">Admin ghim</span>' : '';
        const tooltip = String(doc.description || '').trim();

        const item = document.createElement('div');
        item.className = 'document-item pinned-item' + (isAdminPinned ? ' admin-pinned' : '');
        item.innerHTML = `
            <div class="doc-info">
                <div class="doc-name">
                    <i class="fas fa-thumbtack" style="color: ${isAdminPinned ? '#e74a3b' : '#f6c23e'}; margin-right: 6px;"></i>
                    ${displayName}
                    ${adminLabel}
                </div>
                <div class="doc-meta">
                    <span>${typeLabel}</span>
                    ${folderLabel ? `<span>${folderLabel}</span>` : ''}
                </div>
            </div>
            <div class="kebab-menu-wrapper">
                <button type="button" class="kebab-menu-btn" title="Tùy chọn">
                    <i class="fas fa-ellipsis-v"></i>
                </button>
                <div class="kebab-menu-dropdown">
                    <div class="kebab-menu-item" onclick="event.stopPropagation(); toggleDocumentSelection({type: '${doc.document_type}', id: ${doc.document_id}, filename: '${doc.filename}', label: '${displayName.replace(/'/g, "\\'")}'}); closeAllKebabMenus();">
                        <i class="fas fa-comment-dots"></i> Dùng để hỏi
                    </div>
                    <div class="kebab-menu-item" onclick="event.stopPropagation(); downloadDocument('${doc.document_type}', ${doc.document_id}, '${doc.filename}'); closeAllKebabMenus();">
                        <i class="fas fa-download"></i> Tải về
                    </div>
                    ${!isAdminPinned ? `
                    <div class="kebab-menu-item delete-item" onclick="event.stopPropagation(); unpinDocument(${doc.document_id}, '${doc.document_type}'); closeAllKebabMenus();">
                        <i class="fas fa-thumbtack"></i> Bỏ ghim
                    </div>
                    ` : ''}
                </div>
            </div>
        `;

        if (tooltip) {
            item.title = tooltip;
            const nameEl = item.querySelector('.doc-name');
            if (nameEl) nameEl.title = tooltip;
        }

        // Add click handler for kebab button
        const kebabBtn = item.querySelector('.kebab-menu-btn');
        kebabBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            closeAllKebabMenus();
            item.querySelector('.kebab-menu-dropdown').classList.toggle('show');
        });

        item.onclick = (e) => {
            if (e.target.closest('.kebab-menu-wrapper')) return;
            const chatInput = document.getElementById('chatInput');
            if (chatInput) {
                chatInput.value = `Tài liệu ${displayName} nói về nội dung gì?`;
                chatInput.focus();
            }
        };

        container.appendChild(item);
    });
}

async function checkPinStatus(docId, docType) {
    try {
        const endpoint = docType === 'company'
            ? `/documents/${docId}/pin-status`
            : `/user-documents/${docId}/pin-status`;

        const response = await fetch(`${API_URL}${endpoint}`, {
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            return data.pinned || false;
        }
        return false;
    } catch (error) {
        console.error('Error checking pin status:', error);
        return false;
    }
}

async function pinDocument(docId, docType) {
    try {
        const endpoint = docType === 'company'
            ? `/documents/${docId}/pin`
            : `/user-documents/${docId}/pin`;

        const response = await fetch(`${API_URL}${endpoint}`, {
            method: 'POST',
            credentials: 'include'
        });

        const data = await response.json();

        if (data.success) {
            showNotification('Đã ghim tài liệu', 'success');
            // Update UI
            updatePinButton(docId, docType, true);
        } else {
            showNotification(data.error || 'Không thể ghim tài liệu', 'error');
        }
    } catch (error) {
        console.error('Error pinning document:', error);
        showNotification('Lỗi khi ghim tài liệu', 'error');
    }
}

async function unpinDocument(docId, docType) {
    try {
        const endpoint = docType === 'company'
            ? `/documents/${docId}/unpin`
            : `/user-documents/${docId}/unpin`;

        const response = await fetch(`${API_URL}${endpoint}`, {
            method: 'POST',
            credentials: 'include'
        });

        const data = await response.json();

        if (data.success) {
            showNotification('Đã bỏ ghim tài liệu', 'success');
            // Refresh pinned list
            loadPinnedDocuments();
            // Update UI in other tabs
            updatePinButton(docId, docType, false);
        } else {
            showNotification(data.error || 'Không thể bỏ ghim tài liệu', 'error');
        }
    } catch (error) {
        console.error('Error unpinning document:', error);
        showNotification('Lỗi khi bỏ ghim tài liệu', 'error');
    }
}

function updatePinButton(docId, docType, isPinned) {
    // Find and update pin menu items in document lists (kebab menus)
    const selector = `[data-doc-id="${docId}"][data-doc-type="${docType}"] .pin-menu-item`;
    const pinItems = document.querySelectorAll(selector);

    pinItems.forEach(item => {
        if (isPinned) {
            item.classList.add('pinned');
            item.innerHTML = '<i class="fas fa-thumbtack"></i> Bỏ ghim';
        } else {
            item.classList.remove('pinned');
            item.innerHTML = '<i class="fas fa-thumbtack"></i> Ghim';
        }
    });

    // Also update old .pin-btn buttons if they exist
    const oldBtnSelector = `[data-doc-id="${docId}"][data-doc-type="${docType}"] .pin-btn`;
    const oldButtons = document.querySelectorAll(oldBtnSelector);

    oldButtons.forEach(btn => {
        if (isPinned) {
            btn.innerHTML = '<i class="fas fa-thumbtack" style="color: #f6c23e;"></i>';
            btn.title = 'Bỏ ghim';
            btn.onclick = () => unpinDocument(docId, docType);
        } else {
            btn.innerHTML = '<i class="fas fa-thumbtack"></i>';
            btn.title = 'Ghim';
            btn.onclick = () => pinDocument(docId, docType);
        }
    });
}

function showNotification(message, type = 'info') {
    // Simple notification - you can enhance this
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        border-radius: 6px;
        background: ${type === 'success' ? '#1cc88a' : type === 'error' ? '#e74a3b' : '#4e73df'};
        color: white;
        font-size: 14px;
        z-index: 10000;
        box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        animation: slideIn 0.3s ease;
    `;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// ==================== PERSONAL FOLDER MANAGEMENT ====================

function showRenamePersonalFolderModal(folderName) {
    const newName = prompt(`Đổi tên thư mục "${folderName}" thành:`, folderName);
    if (newName && newName.trim() && newName.trim() !== folderName) {
        renamePersonalFolder(folderName, newName.trim());
    }
}

async function renamePersonalFolder(oldName, newName) {
    try {
        const response = await fetch(`${API_URL}/user-documents/folders/rename`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ old_name: oldName, new_name: newName })
        });

        const data = await response.json();

        if (data.success) {
            showNotification('Đã đổi tên thư mục', 'success');
            loadPersonalDocuments();
            loadFoldersForUpload();
        } else {
            showNotification(data.error || 'Không thể đổi tên thư mục', 'error');
        }
    } catch (error) {
        console.error('Error renaming folder:', error);
        showNotification('Lỗi khi đổi tên thư mục', 'error');
    }
}

async function deletePersonalFolder(folderName) {
    if (!confirm(`Xóa thư mục "${folderName}"? Tất cả tài liệu trong thư mục sẽ bị xóa.`)) {
        return;
    }

    try {
        const response = await fetch(`${API_URL}/user-documents/folders/delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ folder_name: folderName })
        });

        const data = await response.json();

        if (data.success) {
            showNotification('Đã xóa thư mục', 'success');
            loadPersonalDocuments();
            loadFoldersForUpload();
        } else {
            showNotification(data.error || 'Không thể xóa thư mục', 'error');
        }
    } catch (error) {
        console.error('Error deleting folder:', error);
        showNotification('Lỗi khi xóa thư mục', 'error');
    }
}

// ==================== PERSONAL FILE MANAGEMENT ====================

function showRenamePersonalFileModal(docId, currentName) {
    const newName = prompt(`Đổi tên tài liệu "${currentName}" thành:`, currentName);
    if (newName && newName.trim() && newName.trim() !== currentName) {
        renamePersonalFile(docId, newName.trim());
    }
}

async function renamePersonalFile(docId, newName) {
    try {
        const response = await fetch(`${API_URL}/user-documents/${docId}/rename`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ new_name: newName })
        });

        const data = await response.json();

        if (data.success) {
            showNotification('Đã đổi tên tài liệu', 'success');
            loadPersonalDocuments();
        } else {
            showNotification(data.error || 'Không thể đổi tên tài liệu', 'error');
        }
    } catch (error) {
        console.error('Error renaming file:', error);
        showNotification('Lỗi khi đổi tên tài liệu', 'error');
    }
}

async function loadFoldersForUpload() {
    try {
        const folderSelect = document.getElementById('uploadFolderSelect');
        if (!folderSelect) return;
        
        // Start with "create new" option
        folderSelect.innerHTML = '<option value="">-- Chọn thư mục hoặc tạo mới bên dưới --</option>';
        
        // Fetch user's existing folders
        const response = await fetch(`${API_URL}/user-documents/my-folders`, {
            credentials: 'include'
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.success && data.folders && data.folders.length > 0) {
                // Add separator
                const separator = document.createElement('optgroup');
                separator.label = 'Thư mục của bạn';
                
                data.folders.forEach(folder => {
                    const option = document.createElement('option');
                    option.value = folder.name;
                    option.textContent = `📁 ${folder.name} (${folder.count} tài liệu)`;
                    separator.appendChild(option);
                });
                
                folderSelect.appendChild(separator);
            }
        }
    } catch (error) {
        console.error('Error loading folders for upload:', error);
    }
}

async function handleUpload(e) {
    e.preventDefault();

    const fileInput = document.getElementById('fileInput');
    const descInput = document.getElementById('descriptionInput');
    const submitBtn = e.target.querySelector('button[type="submit"]');

    if (!fileInput.files[0]) {
        alert('Vui lòng chọn một tập tin');
        return;
    }

    const folderSelect = document.getElementById('uploadFolderSelect');
    const newFolderInput = document.getElementById('newFolderInput');
    
    // Use new folder name if provided, otherwise use selected folder, default to 'Chung'
    let selectedFolder = 'Chung';
    if (newFolderInput && newFolderInput.value.trim()) {
        selectedFolder = newFolderInput.value.trim();
    } else if (folderSelect && folderSelect.value && folderSelect.value.trim()) {
        selectedFolder = folderSelect.value.trim();
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('description', descInput.value);
    formData.append('role', currentRole);
    formData.append('folder', selectedFolder);

    submitBtn.disabled = true;
    submitBtn.textContent = '⏳ Đang tải lên...';

    try {
        const response = await fetch(`${API_URL}/user-documents/upload`, {
            method: 'POST',
            credentials: 'include',
            body: formData
        });

        if (response.ok) {
            submitBtn.textContent = '✅ Đã tải lên!';
            fileInput.value = '';
            descInput.value = '';
            if (newFolderInput) newFolderInput.value = '';

            setTimeout(() => {
                submitBtn.textContent = 'Tải lên Tài liệu';
                submitBtn.disabled = false;
            }, 2000);

            await loadPersonalDocuments(); // Reload personal documents to show new file
            await loadFoldersForUpload(); // Refresh folder list in upload dropdown
            showNotification('Tải tài liệu thành công!', 'success');
        } else {
            const error = await response.json();
            alert('Tải lên thất bại: ' + (error.error || 'Lỗi không xác định'));
            submitBtn.textContent = 'Tải lên Tài liệu';
            submitBtn.disabled = false;
        }
    } catch (error) {
        console.error('Upload error:', error);
        alert('Tải lên thất bại: Lỗi mạng');
        submitBtn.textContent = 'Tải lên Tài liệu';
        submitBtn.disabled = false;
    }
}

// Utility Functions
function formatDate(dateString) {
    if (!dateString) return 'Unknown';

    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 60) return `${diffMins}m trước`;
    if (diffHours < 24) return `${diffHours}h trước`;
    if (diffDays < 7) return `${diffDays}d trước`;

    return date.toLocaleDateString();
}

async function logout() {
    if (!confirm('Bạn có chắc chắn muốn đăng xuất?')) {
        return;
    }

    try {
        await fetch('/api/auth/logout', {
            method: 'POST',
            credentials: 'include'
        });
    } catch (_) {
        // ignore network errors; still clear client state
    } finally {
        localStorage.clear();
        sessionStorage.clear();
        // Server serves the login page at /login
        window.location.href = '/login';
    }
}

// Error handling
window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection:', event.reason);
});

// Report Modal Functions
function openReportModal() {
    const modal = document.getElementById('reportModal');
    if (!modal) return;

    // Get last AI response for reporting context
    const lastEntry = chatHistory[chatHistory.length - 1];
    if (lastEntry) {
        document.getElementById('reportQuestion').value = lastEntry.user || '';
        document.getElementById('reportAnswer').value = lastEntry.ai || '';
    }

    modal.classList.add('show');
}

function openReportModalWithContext(question, answer) {
    const modal = document.getElementById('reportModal');
    if (!modal) return;

    document.getElementById('reportQuestion').value = question || '';
    document.getElementById('reportAnswer').value = answer || '';

    modal.classList.add('show');
}

function closeReportModal() {
    const modal = document.getElementById('reportModal');
    if (modal) {
        modal.classList.remove('show');
    }
}

async function submitReport() {
    const question = document.getElementById('reportQuestion')?.value || '';
    const answer = document.getElementById('reportAnswer')?.value || '';
    const type = document.getElementById('reportType')?.value || 'other';
    const comment = document.getElementById('reportComment')?.value || '';

    if (!comment.trim()) {
        alert('Vui lòng thêm nhận xét mô tả vấn đề.');
        return;
    }

    const btn = document.getElementById('submitReport');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Đang gửi...';
    }

    try {
        const response = await fetch(`${API_URL}/report`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question,
                answer,
                issue_type: type,
                comment,
                session_id: activeSessionId
            })
        });

        if (response.ok) {
            alert('Báo cáo đã gửi. Cảm ơn phản hồi của bạn!');
            closeReportModal();
            document.getElementById('reportComment').value = '';
        } else {
            const err = await response.json().catch(() => ({}));
            alert('Gửi báo cáo thất bại: ' + (err.error || 'Lỗi không xác định'));
        }
    } catch (e) {
        console.error('Report error:', e);
        alert('Lỗi mạng khi gửi báo cáo.');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Gửi Báo cáo';
        }
    }
}

// Download Chat Transcript
function downloadChatTranscript() {
    if (chatHistory.length === 0) {
        alert('No chat history to download.');
        return;
    }

    let transcript = '=== Chat Transcript ===\n\n';
    chatHistory.forEach((entry, idx) => {
        transcript += `--- Exchange ${idx + 1} ---\n`;
        transcript += `User: ${entry.user}\n\n`;
        transcript += `Assistant: ${entry.ai}\n`;
        if (entry.sources && entry.sources.length > 0) {
            transcript += `Sources: ${entry.sources.map(s => typeof s === 'object' ? s.filename : s).join(', ')}\n`;
        }
        transcript += '\n';
    });

    const blob = new Blob([transcript], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat-transcript-${new Date().toISOString().slice(0, 10)}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
