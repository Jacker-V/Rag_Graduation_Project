// Language translations for the UI
const translations = {
    en: {
        // Header
        appTitle: 'Technical Assistant',
        logout: 'Logout',
        
        // Navigation
        documents: 'Documents',
        upload: 'Upload',
        news: 'News',
        chat: 'Chat',
        
        // Document sections
        companyDocuments: 'Company Documents',
        personalDocuments: 'Personal Documents',
        reloadDocuments: 'Reload documents',
        
        // Upload section
        uploadPersonalDocument: 'Upload Personal Document',
        uploadHelp: 'Upload documents to your personal workspace. Files are available immediately.',
        selectFile: 'Select File',
        fileAllowed: 'Allowed: PDF, DOCX, TXT, MD (Max 10MB)',
        description: 'Description',
        descriptionPlaceholder: 'Describe what this document is about...',
        uploadButton: 'Upload Document',
        myUploads: 'My Uploads',
        
        // Document card
        download: 'Download',
        use: 'Use',
        selected: 'Selected',
        summarize: 'Summarize',
        
        // Document queries
        whatIsThisAbout: 'What is this document about?',
        
        // News section
        newsFilter: 'Filter News',
        filterAll: 'All',
        filterToday: 'Today',
        filterWeek: 'This Week',
        refreshNews: 'Refresh News',
        fetchingNews: 'Fetching latest news...',
        explainTerms: 'Explain Terms',
        summarizeArticle: 'Summarize',
        readers: 'readers',
        
        // News queries
        explainTermsQuery: 'Explain all technical terms in the article "{title}" so readers can understand the content',
        summarizeQuery: 'Summarize the article "{title}"',
        
        // Chat section
        typeMessage: 'Type your message...',
        send: 'Send',
        askQuestion: 'Ask a question...',
        clearConversation: 'Clear Conversation',
        selectedDocuments: 'Selected documents',
        noDocumentsSelected: 'No documents selected',
        
        // Role types
        security_engineer: 'Security Engineer',
        devops_engineer: 'DevOps Engineer',
        backend_developer: 'Backend Developer',
        frontend_developer: 'Frontend Developer',
        data_scientist: 'Data Scientist',
        cloud_engineer: 'Cloud Engineer',
        
        // Messages
        loading: 'Loading...',
        noNews: 'No news available',
        error: 'Error',
        success: 'Success',
        
        // Language
        language: 'Language',
    },
    vi: {
        // Header
        appTitle: 'Trợ lý Kỹ thuật',
        logout: 'Đăng xuất',
        
        // Navigation
        documents: 'Tài liệu',
        upload: 'Tải lên',
        news: 'Tin tức',
        chat: 'Trò chuyện',
        
        // Document sections
        companyDocuments: 'Tài liệu Công ty',
        personalDocuments: 'Tài liệu Cá nhân',
        reloadDocuments: 'Tải lại tài liệu',
        
        // Upload section
        uploadPersonalDocument: 'Tải lên Tài liệu Cá nhân',
        uploadHelp: 'Tải lên tài liệu vào không gian làm việc cá nhân. Tài liệu sẽ khả dụng ngay lập tức.',
        selectFile: 'Chọn tập tin',
        fileAllowed: 'Cho phép: PDF, DOCX, TXT, MD (Tối đa 10MB)',
        description: 'Mô tả',
        descriptionPlaceholder: 'Mô tả nội dung tài liệu này...',
        uploadButton: 'Tải lên Tài liệu',
        myUploads: 'Tài liệu của tôi',
        
        // Document card
        download: 'Tải về',
        use: 'Dùng',
        selected: 'Đã chọn',
        summarize: 'Tóm tắt',
        
        // Document queries
        whatIsThisAbout: 'Tài liệu này nói về gì?',
        
        // News section
        newsFilter: 'Lọc tin tức',
        filterAll: 'Tất cả',
        filterToday: 'Hôm nay',
        filterWeek: 'Tuần này',
        refreshNews: 'Làm mới tin tức',
        fetchingNews: 'Đang tải tin tức mới nhất...',
        explainTerms: 'Giải thích thuật ngữ',
        summarizeArticle: 'Tóm tắt',
        readers: 'người đọc',
        
        // News queries
        explainTermsQuery: 'Giải thích tất cả các thuật ngữ kỹ thuật trong bài viết "{title}" để người đọc hiểu rõ nội dung',
        summarizeQuery: 'Tóm tắt bài viết "{title}"',
        
        // Chat section
        typeMessage: 'Nhập tin nhắn...',
        send: 'Gửi',
        askQuestion: 'Đặt câu hỏi...',
        clearConversation: 'Xóa cuộc trò chuyện',
        selectedDocuments: 'Tài liệu đã chọn',
        noDocumentsSelected: 'Chưa chọn tài liệu',
        
        // Role types
        security_engineer: 'Kỹ sư Bảo mật',
        devops_engineer: 'Kỹ sư DevOps',
        backend_developer: 'Lập trình viên Backend',
        frontend_developer: 'Lập trình viên Frontend',
        data_scientist: 'Nhà Khoa học Dữ liệu',
        cloud_engineer: 'Kỹ sư Đám mây',
        
        // Messages
        loading: 'Đang tải...',
        noNews: 'Không có tin tức',
        error: 'Lỗi',
        success: 'Thành công',
        
        // Language
        language: 'Ngôn ngữ',
    }
};

// Current language (default to Vietnamese)
let currentLanguage = localStorage.getItem('preferredLanguage') || 'vi';

// Get translation
function t(key) {
    const keys = key.split('.');
    let value = translations[currentLanguage];
    
    for (const k of keys) {
        value = value?.[k];
        if (value === undefined) break;
    }
    
    // Fallback to English if not found
    if (value === undefined) {
        value = translations['en'];
        for (const k of keys) {
            value = value?.[k];
            if (value === undefined) break;
        }
    }
    
    return value || key;
}

// Switch language
function switchLanguage(lang) {
    if (!translations[lang]) {
        console.warn(`Language ${lang} not supported`);
        return;
    }
    
    currentLanguage = lang;
    localStorage.setItem('preferredLanguage', lang);
    
    // Update UI
    updateUILanguage();
    
    // Dispatch event for components to update
    window.dispatchEvent(new CustomEvent('languageChanged', { detail: { language: lang } }));
}

// Update UI with current language
function updateUILanguage() {
    // This will be called by individual components
    // to update their text content
}

// Export for use in other files
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { t, switchLanguage, currentLanguage, translations };
}
