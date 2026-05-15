# Báo cáo đồ án: Trợ lý tri thức nội bộ dựa trên RAG + LLM

> Lưu ý: Đây là bản thuyết minh chi tiết, phục vụ cả người đọc lẫn người nghe báo cáo, nên giải thích từ tổng quan hệ thống cho đến logic triển khai cụ thể trong code.

## 1. Mục tiêu và bài toán

### 1.1. Bài toán thực tế

Trong một doanh nghiệp/công ty, kiến thức nội bộ thường nằm rải rác:
- Trong các file tài liệu (Word, PDF, slide, policy, quy trình,…)
- Trong hệ thống lưu trữ nội bộ (folder, server, drive,…)
- Trong kinh nghiệm cá nhân của từng nhân sự

Nhân viên mới, hoặc các bộ phận khác nhau (IT, Security, HR, Business,…) thường:
- Khó tìm được đúng tài liệu cần thiết
- Phải hỏi đi hỏi lại các anh/chị có kinh nghiệm
- Mất thời gian đọc rất nhiều tài liệu dài dòng

Đồ án xây dựng **Trợ lý tri thức nội bộ** nhằm giải quyết bài toán trên:
- Cho phép upload, quản lý, gắn nhãn và phê duyệt tài liệu nội bộ
- Tự động index (nhúng vector) và lưu trữ dưới dạng vector để hỗ trợ truy vấn
- Cung cấp giao diện chat để nhân viên hỏi – hệ thống trả lời dựa trên kiến thức nội bộ
- Bổ sung tính năng **tin tức an ninh/công nghệ** để cập nhật tin mới và giải thích lại bằng ngôn ngữ dễ hiểu

### 1.2. Mục tiêu cụ thể

1. Xây dựng hệ thống RAG (Retrieval-Augmented Generation) hoàn chỉnh:
   - Ingestion tài liệu (đọc file, chia nhỏ chunk, nhúng vector)
   - Lưu vector vào kho (vector store)
   - Truy vấn lại các đoạn liên quan khi người dùng đặt câu hỏi
   - Kết hợp LLM để sinh câu trả lời dựa trên ngữ cảnh truy vấn được
2. Hỗ trợ nhiều nguồn kiến thức:
   - Tài liệu công ty (do admin quản lý)
   - Tài liệu do người dùng upload (có phê duyệt thành “tài liệu cá nhân”)
   - Tin tức kỹ thuật/an ninh mạng từ internet
3. Xây dựng 2 giao diện web tách biệt:
   - **Admin UI**: upload, phê duyệt tài liệu, xem thống kê, quản lý báo cáo lỗi
   - **User UI**: giao diện chat, xem tài liệu cá nhân, xem “my uploads”, xem & tóm tắt tin tức
4. Hỗ trợ nhiều nhà cung cấp LLM:
   - Gemini (mặc định), OpenRouter, Ollama (local)
   - Dễ cấu hình bằng biến môi trường
5. Thiết kế hệ thống để có thể triển khai lên server (Docker, docker-compose, Makefile).

---

## 2. Giải thích các khái niệm (term) quan trọng

Trước khi đi sâu vào kiến trúc, cần làm rõ một số khái niệm thường xuyên xuất hiện trong đồ án. Đây cũng là những chỗ rất hay bị hỏi trong buổi bảo vệ.

### 2.1. LLM (Large Language Model)

- Là mô hình ngôn ngữ lớn được huấn luyện trên lượng dữ liệu văn bản khổng lồ.
- Có khả năng:
   - Sinh văn bản (text generation)
   - Trả lời câu hỏi (question answering)
   - Tóm tắt (summarization)
   - Dịch thuật, viết code, giải thích lỗi,…
- Trong đồ án, LLM **không tự biết** kiến thức nội bộ của công ty. Nó chỉ biết kiến thức chung (public) mà nó được huấn luyện trước đó.

### 2.2. RAG (Retrieval-Augmented Generation)

- Là kỹ thuật kết hợp **hai bước**:
   1. **Retrieval**: truy xuất (lấy ra) các đoạn tài liệu liên quan từ kho tri thức nội bộ.
   2. **Generation**: dùng LLM để sinh câu trả lời **dựa trên đoạn tài liệu đã truy xuất**.
- Ý nghĩa:
   - Giúp LLM “biết” kiến thức nội bộ mà không cần phải huấn luyện lại toàn bộ mô hình.
   - Câu trả lời bám sát tài liệu nội bộ → dễ kiểm chứng, dễ giải thích.

Ví dụ:
- User hỏi: "Quy trình onboarding nhân viên mới bên công ty mình như thế nào?"
- Bước 1 (Retrieval): hệ thống tìm trong các file tài liệu nội bộ xem có file policy/quy trình liên quan.
- Bước 2 (Generation): LLM đọc những đoạn được tìm thấy và tóm tắt lại bằng tiếng Việt dễ hiểu.

### 2.3. Embedding (vector hoá văn bản)

- Embedding là cách biến một đoạn văn bản thành một vector số học (ví dụ 768 chiều).
- Đặc tính quan trọng: **các đoạn văn bản giống nhau về nghĩa sẽ có vector gần nhau trong không gian vector**.
- Công dụng trong hệ thống:
   - Thay vì so khớp string (từ khoá), ta so khớp **ngữ nghĩa** giữa câu hỏi và các đoạn tài liệu.
   - Giúp trả lời cả khi user không dùng đúng từ khoá như trong tài liệu.

### 2.4. Vector store (kho vector)

- Là nơi lưu trữ tất cả các embedding của tài liệu nội bộ.
- Cho phép các thao tác:
   - Thêm mới embedding (khi ingest tài liệu).
   - Tìm các vector gần nhất với vector của câu hỏi (nearest neighbors search).
- Trong đồ án, vector store được triển khai theo cách đơn giản (tuỳ vào thư viện và cấu hình), nhưng khái niệm chung là giống nhau: **một kho để tìm kiếm theo độ tương đồng vector**.

### 2.5. Chunking (chia nhỏ tài liệu)

- Tài liệu thực tế thường rất dài (vài chục – vài trăm trang).
- Không thể nhét nguyên cả tài liệu vào một embedding duy nhất hoặc đưa nguyên vào LLM.
- Chunking là bước **cắt tài liệu thành nhiều đoạn nhỏ** (ví dụ 500–1000 từ), mỗi đoạn:
   - Được nhúng thành một embedding riêng.
   - Được lưu riêng trong vector store kèm metadata.
- Khi user hỏi, hệ thống chỉ cần lấy 3–5 chunk **gần nhất** thay vì cả file.

### 2.6. Prompt & Prompt Template

- Prompt: đoạn text mà ta gửi cho LLM, bao gồm:
   - Hướng dẫn (instruction): "Bạn là trợ lý tri thức nội bộ, hãy trả lời ngắn gọn, bằng tiếng Việt,…"
   - Ngữ cảnh (context): các đoạn tài liệu truy xuất được từ RAG.
   - Câu hỏi của người dùng.
- Prompt template: khung mẫu được code sẵn (ở `rag_chatbot/core/prompt/*.py`), trong đó có các placeholder để chèn context và câu hỏi.

### 2.7. Session, chat history

- Session: đại diện cho một phiên chat (từ lúc user mở trang đến khi đóng hoặc reset).
- Chat history: toàn bộ hội thoại trong một session, gồm:
   - Câu hỏi của user
   - Câu trả lời của hệ thống
   - Thời gian, metadata khác
- Lưu session giúp:
   - Backend có thể giữ ngữ cảnh qua nhiều lượt hỏi
   - Phục vụ phân tích/logging sau này

---

## 3. Kiến trúc tổng thể hệ thống

### 2.1. Các khối chức năng chính

Hệ thống được chia thành các khối lớn sau:

1. **Giao diện người dùng (Frontend)** – thư mục `UI/`
   - `user_index.html`, `src/user/main.js`, `user_styles.css`: giao diện người dùng cuối
   - `admin_index.html`, `src/admin/main.js`, `admin_styles.css`: giao diện admin

2. **Backend Flask** – các file chạy chính:
   - `run_user_web.py`: backend phục vụ user UI
   - `run_admin_web.py`: backend phục vụ admin UI

3. **Lõi RAG & mô hình LLM** – thư mục `rag_chatbot/core/`:
   - `ingestion/ingestion.py`: pipeline đọc, chia nhỏ và đưa tài liệu vào hệ thống
   - `embedding/embedding.py`: nhúng văn bản thành vector
   - `vector_store/vector_store.py`: lưu trữ và truy vấn vector
   - `engine/engine.py`, `engine/retriever.py`: logic RAG engine, truy xuất ngữ cảnh
   - `model/model.py`: wrapper chọn LLM provider (Gemini/OpenRouter/Ollama)
   - `prompt/*.py`: template prompt cho QA, query generation, selection,…

4. **Quản lý dữ liệu & CSDL** – thư mục `rag_chatbot/`:
   - `database.py`: quản lý SQLite DB (user, tài liệu, tin tức, lịch sử chat,…)
   - `eval/`, `test/`: phục vụ kiểm thử & đánh giá

5. **Tin tức kỹ thuật (News)** – `rag_chatbot/workers/news_fetcher.py` + logic trong `run_user_web.py`:
   - Lấy RSS feed từ các nguồn như The Hacker News,…
   - Crawl nội dung đầy đủ bài báo
   - Lưu vào bảng `technical_articles`
   - Cho phép người dùng xem & yêu cầu tóm tắt/giải thích

6. **Triển khai & môi trường**:
   - `Dockerfile`, `docker-compose.yml`, `Makefile`, `pyproject.toml`: cấu hình build & chạy

### 2.2. Luồng dữ liệu chính

1. **Tài liệu nội bộ**:
   - Admin upload file → Backend lưu file vật lý + metadata vào DB → Pipeline ingestion đọc file, chia chunk, nhúng → lưu vector vào vector store → Lúc user hỏi, RAG Engine truy vấn vector → trả lời kèm trích dẫn ngữ cảnh.

2. **Tin tức kỹ thuật**:
   - Worker `news_fetcher` lấy RSS → lưu metadata bài báo → khi user bấm “Tóm tắt bài báo”, backend crawl nội dung đầy đủ, làm sạch HTML, tách đoạn → gửi vào LLM để sinh tóm tắt → lưu và hiển thị lên UI.

3. **Chat Q&A nội bộ**:
   - User nhập câu hỏi trong `user_index.html` → `UI/src/user/main.js` gọi API → Backend lấy lịch sử, truy vấn RAG → LLM sinh câu trả lời → lưu lịch sử chat → UI hiển thị.

---

## 4. Chi tiết backend: Flask, DB, và RAG pipeline

### 3.1. Quản lý CSDL và dữ liệu nội bộ (`rag_chatbot/database.py`)

Hệ thống sử dụng SQLite (file `.db`) để lưu:
- Thông tin người dùng (auth, role: admin/user)
- Bảng tài liệu nội bộ, tài liệu người dùng upload
- Bảng tin tức (`news_sources`, `technical_articles`)
- Bảng lịch sử chat, logs
- Bảng báo cáo lỗi từ người dùng (nếu có)

Một số class quan trọng:

- `UserDocumentManager`:
  - Lưu thông tin file user upload: đường dẫn, trạng thái (pending/approved/rejected), ai upload, thời gian upload
  - Liên kết sang DB auth để lấy thông tin người dùng (tên, email, role)
  - Cung cấp API cho admin:
    - Lấy danh sách tài liệu pending để phê duyệt
   - Phê duyệt/reject tài liệu → khi approved thì trở thành tài liệu “cá nhân”

- `NewsManager`:
  - Lưu nguồn tin tức (RSS feed)
  - Lưu từng bài báo kỹ thuật: title, url, published_at, content (text đầy đủ), role liên quan
  - Cung cấp API cho backend lấy danh sách bài theo role người dùng

- `ChatHistoryManager` (tuỳ tên cụ thể trong code):
  - Lưu lại mỗi câu hỏi – câu trả lời, session id, thời gian
  - Phục vụ cả cho việc debug và cải thiện mô hình sau này

### 3.2. Pipeline RAG (`rag_chatbot/core/*`)

#### 3.2.1. Ingestion – `ingestion/ingestion.py`

Chức năng:
- Đọc file tài liệu từ ổ đĩa (PDF, DOCX, TXT,…)
- Chuẩn hoá văn bản (loại bỏ các ký tự thừa nếu cần)
- Chia nhỏ tài liệu thành nhiều đoạn (chunk) theo kích thước token/ký tự
- Gắn metadata: tên file, loại tài liệu, role, người upload, thời gian
- Gửi các chunk này qua bước embedding

Lưu ý quan trọng:
- Việc chia chunk giúp RAG không phải đưa cả tài liệu dài vào LLM, mà chỉ dùng các đoạn liên quan.
- Metadata cho phép filter tài liệu theo role (ví dụ: tài liệu chỉ cho bộ phận Security, hay chỉ nhóm cá nhân cụ thể,…).

#### 3.2.2. Embedding – `embedding/embedding.py`

Chức năng:
- Chuyển mỗi đoạn văn bản (chunk) thành một vector số học (embedding)
- Thường sử dụng mô hình embedding từ `llama_index` hoặc các provider hỗ trợ
- Trả về vector + metadata để lưu trữ

Điểm kỹ thuật:
- Có thể cấu hình model embedding (ví dụ: OpenAI, local, hay embedding của Gemini/OpenRouter)
- Cần đảm bảo encoding thống nhất giữa lúc index và lúc truy vấn

#### 3.2.3. Vector Store – `vector_store/vector_store.py`

Chức năng:
- Lưu các embedding vào một kho (có thể là SQLite, file, hay thư viện chuyên dụng tuỳ config)
- Cung cấp API:
  - `add_documents(chunks)` – thêm mới các document embedding
  - `query(query_embedding, top_k)` – trả về các đoạn gần nhất với câu hỏi

Đây là phần quyết định **tốc độ** và **chất lượng truy vấn** của RAG.

#### 3.2.4. Retrieval & Chat Engine – `engine/engine.py`, `engine/retriever.py`

Chức năng:
- Nhận câu hỏi từ user → tạo embedding cho câu hỏi
- Gọi vector store để lấy ra top-k đoạn liên quan nhất
- Kết hợp các đoạn đó thành ngữ cảnh (context) cho LLM
- Áp dụng prompt template (ở `prompt/qa_prompt.py`,…)
- Gọi LLM để sinh câu trả lời cuối cùng

`LocalRAGPipeline` đóng vai trò “orchestrator”: gom các bước trên thành một hàm call duy nhất cho backend.

### 3.3. Lớp mô hình LLM (`core/model/model.py`)

Mục tiêu: trừu tượng hoá việc gọi LLM, để backend chỉ cần gọi một API thống nhất.

- Dựa vào biến môi trường `LLM_PROVIDER`, hệ thống chọn:
  - **Gemini** – thông qua API key
  - **OpenRouter** – route nhiều model khác nhau
  - **Ollama** – dùng mô hình local trên máy

- Lớp wrapper cung cấp hàm như:
  - `complete(prompt, ...)` – sinh text từ prompt
  - Có thể dùng thêm các tham số như `temperature`, `max_tokens`, `system_prompt`,…

Đối với tính năng tóm tắt tin tức, backend trực tiếp dùng `pipeline._default_model.complete(...)` để gọi đúng provider đã cấu hình.

---

## 5. Chi tiết backend: API cho Admin và User

### 4.1. Backend User – `run_user_web.py`

Các nhóm API chính:

1. **API Chat**:
   - Nhận câu hỏi từ user (kèm session id)
   - Lấy thông tin user, role, context
   - Gọi pipeline RAG để lấy câu trả lời
   - Lưu lịch sử chat vào DB

2. **API Tin tức (News)**:
   - Lấy danh sách bài báo theo role (ví dụ: Security, DevOps,…)
   - Endpoint tóm tắt bài báo: `/api/news/summarize/<article_id>`
     - Tìm bài báo trong DB bằng `NewsManager`
     - Nếu chưa có full content hoặc content quá ngắn → gọi `NewsFetcher.fetch_article_content(url)` để crawl lại
     - Làm sạch HTML, loại bỏ các đoạn quảng cáo / snippet không liên quan
     - Tính toán số từ (word count) để đảm bảo nội dung đủ dài
     - Gọi LLM để sinh tóm tắt tự nhiên (giải thích ngắn gọn, dễ hiểu, kèm bối cảnh, tác động, khuyến nghị)
     - Nếu LLM gặp lỗi → fallback sang các hàm heuristic `build_structured_brief` hoặc `build_article_summary`

3. **API Tài liệu**:
   - Lấy danh sách tài liệu cá nhân (đã được admin phê duyệt)
   - Lấy danh sách “My uploads” cho user hiện tại
   - Cho phép upload tài liệu mới (tuỳ quyền user/role)

4. **API Khác**:
   - Lấy role người dùng hiện tại
   - Gửi báo cáo lỗi, góp ý,…

### 4.2. Backend Admin – `run_admin_web.py`

Các nhóm API chính:

1. **Quản lý tài liệu**:
   - Lấy danh sách tài liệu pending để phê duyệt
   - Approve/Reject tài liệu → cập nhật trạng thái trong DB
   - Xem chi tiết metadata từng tài liệu (uploader, role, thời gian, mô tả,…)

2. **Quản lý tin tức & thống kê**:
   - Xem thống kê số lượng tài liệu, số lượng người dùng, số lượng câu hỏi,…
   - Theo dõi trạng thái worker tin tức (số bài báo mới, nguồn, ngày cập nhật,…)

3. **Quản lý báo cáo lỗi/feedback**:
   - Xem danh sách lỗi người dùng gửi từ giao diện chat
   - Đánh dấu đã xử lý / đang xử lý

Admin UI sử dụng các endpoint này để xây dựng một bảng điều khiển (dashboard) trực quan, hiện đại.

---

## 6. Giao diện người dùng (Frontend)

### 5.1. User UI – `UI/user_index.html`, `UI/src/user/main.js`, `UI/user_styles.css`

#### 5.1.1. Chức năng chính

1. **Giao diện chat**:
   - Khung chat hiển thị hội thoại (user – AI)
   - Input để người dùng nhập câu hỏi
   - Hỗ trợ nhấn Enter để gửi, hiển thị trạng thái đang xử lý

2. **Danh sách tài liệu**:
   - Tab “Tài liệu công ty”: hiển thị tài liệu đã được admin index
   - Tab “Tài liệu cá nhân”: tài liệu do người dùng upload và admin đã phê duyệt
   - Tab “My uploads”: tất cả tài liệu mà user hiện tại đã upload (kèm trạng thái)

3. **Tin tức kỹ thuật**:
   - Danh sách card bài báo: tiêu đề, nguồn, thời gian, mô tả ngắn
   - Nút **“Tóm tắt bài báo”** trên mỗi card
     - Khi bấm → gọi API `/api/news/summarize/<id>`
     - Hiển thị câu hỏi giả lập (ví dụ: "Hãy tóm tắt bài báo này cho tôi") + câu trả lời của AI trong vùng chat

4. **Báo cáo lỗi/feedback**:
   - Cho phép user gửi feedback nếu câu trả lời không đúng hoặc có lỗi hệ thống

#### 5.1.2. Logic trong `UI/src/user/main.js`

- `createNewsCard(article)`:
  - Tạo DOM hiển thị card tin tức với nút tóm tắt
  - Gắn event click vào nút để gọi `summarizeNewsArticle(article.id)`

- `summarizeNewsArticle(articleId)`:
  - Gửi POST request tới backend kèm `session_id`
  - Khi nhận response:
    - Thêm một “message” mới vào UI cho phần câu hỏi (dạng giả lập)
    - Thêm message cho phần câu trả lời (tóm tắt từ backend)
  - Không còn tự động điền text vào ô chat để tránh làm rối input của người dùng

- `displayPersonalDocuments`, `displayMyUploads`:
  - Render danh sách tài liệu với thông tin chi tiết: tên file, người upload, trạng thái, thời gian
  - Dùng metadata từ backend (bao gồm uploader_name) đã được xử lý trong `UserDocumentManager`

### 6.2. Admin UI – `UI/admin_index.html`, `UI/src/admin/main.js`, `UI/admin_styles.css`

#### 5.2.1. Mục tiêu thiết kế

- Giao diện hiện đại, trực quan:
  - Sidebar cố định bên trái
  - Topbar với nút toggle sidebar, thanh tìm kiếm, icon thông báo
  - Vùng nội dung hiển thị từng page: Dashboard, Tài liệu, Tin tức, Báo cáo,…

- Các component chính:
  - **Stats cards**: hiển thị tổng số tài liệu, user, câu hỏi, lỗi,…
  - **Tables**: danh sách tài liệu pending, danh sách báo cáo
  - **Upload area**: vùng upload drag & drop cho tài liệu
  - **Badge/Status**: hiển thị trạng thái tài liệu (pending/approved/rejected) với màu sắc đặc trưng
  - **Modal**: popup xem chi tiết hoặc xác nhận hành động (duyệt, từ chối,…)

#### 5.2.2. File `admin_styles.css` và lỗi syntax đầu file

- Ở 4 dòng đầu của file trước khi sửa, code đang là:
  - `margin-bottom: 8px;`
  - `color: var(--dark);`
  - `line-height: 1.5;`
  - `}`

Lỗi ở đây:
- Trong CSS, mọi thuộc tính (`margin-bottom`, `color`, `line-height`) **phải nằm trong một block selector** dạng:

```css
.selector {
    property: value;
}
```

- 4 dòng đầu tiên lại là các thuộc tính **đứng một mình, không có selector mở `{`** tương ứng → trình duyệt coi đây là **syntax error**, có thể bỏ qua cả block CSS tiếp theo.

Cách sửa hợp lý (phù hợp với phần phía sau có selector `.list-item p:last-child`) là gộp chúng vào một selector đầy đủ, ví dụ ` .list-item p `:

```css
.list-item p {
    margin-bottom: 8px;
    color: var(--dark);
    line-height: 1.5;
}
```

Trong repo, phần sửa đã được áp dụng theo đúng hướng này để CSS hợp lệ và hoạt động đúng.

---

## 7. Các tính năng chính & luồng hoạt động chi tiết

Phần này đi theo hướng "kể chuyện" từng use case cụ thể mà giảng viên thường hỏi, giúp thấy rõ hệ thống hoạt động thế nào từ góc nhìn người dùng.

### 7.1. Use case 1: Nhân viên hỏi về tài liệu nội bộ

**Kịch bản**: Nhân viên mới vào công ty, muốn hỏi: "Các chính sách bảo mật khi làm remote là gì?".

**Các bước chi tiết:**

1. Nhân viên mở User UI (`user_index.html`):
   - Giao diện hiển thị khung chat và các tab tài liệu.
2. Nhân viên gõ câu hỏi vào ô chat và nhấn gửi:
   - `UI/src/user/main.js` gọi API chat ở `run_user_web.py`, gửi:
     - Nội dung câu hỏi
     - session id hiện tại
     - thông tin user (lấy từ session/login)
3. Backend nhận request:
   - Log lại câu hỏi vào bảng chat history (nếu thiết kế theo hướng này).
   - Gửi câu hỏi sang pipeline RAG (`LocalRAGPipeline`).
4. Pipeline RAG:
   - Tạo embedding cho câu hỏi.
   - Truy vấn vector store để lấy top-k đoạn tài liệu liên quan (ví dụ các chính sách bảo mật, quy trình remote,…).
   - Đóng gói các đoạn này thành context, chèn vào prompt template QA.
   - Gọi LLM để sinh câu trả lời cuối.
5. Backend nhận câu trả lời từ LLM:
   - Lưu vào chat history (DB).
   - Trả về JSON cho frontend.
6. User UI:
   - Hiển thị câu trả lời từ AI trong khung chat.
   - Người dùng có thể hỏi tiếp các câu liên quan trong cùng session, pipeline có thể tận dụng lịch sử.

**Điểm hay bị hỏi khi bảo vệ:**
- Hỏi: "Làm sao đảm bảo câu trả lời dựa trên tài liệu nội bộ chứ không phải kiến thức bừa của model?"
  - Trả lời: Vì pipeline **bắt buộc** luôn đưa context (các đoạn tài liệu nội bộ) vào prompt. Prompt được thiết kế theo kiểu: "Dưới đây là các trích đoạn tài liệu nội bộ, hãy trả lời **chỉ dựa trên** chúng".
- Hỏi: "Nếu tài liệu không có nội dung liên quan thì sao?"
  - Trả lời: Khi retrieval trả về độ tương đồng thấp hoặc không tìm thấy chunk tốt, có thể:
    - Trả lời: "Không tìm thấy thông tin trong tài liệu nội bộ".
    - Hoặc chuyển sang chế độ general LLM (tuỳ thiết kế, có thể nói rõ trong đồ án).

### 7.2. Use case 2: Admin upload & phê duyệt tài liệu

**Kịch bản**: Admin muốn thêm một bộ policy mới cho toàn bộ công ty.

**Các bước:**

1. Admin login vào Admin UI (`admin_index.html`).
2. Vào trang "Quản lý tài liệu" với khu vực upload:
   - Logic admin nằm trong `UI/src/admin/main.js` (ES modules).
3. Admin chọn file (`.pdf`, `.docx`, `.txt`,…) và bấm upload:
   - Frontend gửi file qua API upload ở `run_admin_web.py`.
4. Backend:
   - Lưu file vào thư mục lưu trữ.
   - Ghi metadata vào DB: tên file, người upload, thời gian, role áp dụng (VD: toàn công ty / riêng Security,…).
   - Đưa tài liệu vào hàng đợi hoặc gọi trực tiếp pipeline ingestion để:
     - Đọc nội dung file.
     - Chunking, embedding.
     - Lưu vector vào vector store.
5. Nếu là tài liệu do user thường upload:
   - Tài liệu ban đầu ở trạng thái **pending**.
   - Admin vào trang phê duyệt, xem nội dung tóm tắt/metadata.
   - Bấm Approve/Reject.
   - Khi Approve, tài liệu sẽ xuất hiện trong tab "Tài liệu cá nhân" cho các user liên quan.

**Điểm hay bị hỏi:**
- Hỏi: "Nếu upload file rất lớn, hệ thống có bị treo không?"
  - Trả lời: Pipeline chia file thành nhiều chunk, xử lý lần lượt. Có thể thiết kế thêm cơ chế xử lý bất đồng bộ (worker) nếu triển khai lớn.
- Hỏi: "Làm sao để đảm bảo chỉ tài liệu đã được phê duyệt mới được dùng để trả lời?"
  - Trả lời: Trong DB có trường trạng thái (pending/approved/rejected). Retrieval chỉ query trên các document có trạng thái approved.

### 7.3. Use case 3: Xem và tóm tắt tin tức kỹ thuật

**Kịch bản**: Nhân viên Security muốn xem nhanh các lỗ hổng mới được báo trên The Hacker News.

**Các bước:**

1. Worker `news_fetcher` chạy định kỳ:
   - Đọc RSS từ các nguồn đã cấu hình.
   - Lưu danh sách bài báo mới vào bảng `technical_articles` (title, url, summary ngắn,…).
2. User mở tab "Tin tức" trong User UI:
   - Frontend gọi API lấy danh sách bài theo role (vd: Security).
   - Hiển thị danh sách card với tiêu đề, nguồn, thời gian, mô tả ngắn.
3. User bấm nút "Tóm tắt bài báo":
   - Gọi API `/api/news/summarize/<article_id>` như đã mô tả ở phần 7.
4. Backend:
   - Nếu chưa có full content hoặc content quá ngắn → crawl lại bằng `NewsFetcher.fetch_article_content`.
   - Làm sạch HTML, bỏ đoạn quảng cáo.
   - Gọi LLM để tóm tắt bằng ngôn ngữ dễ hiểu.
5. UI:
   - Thêm đoạn QA vào khung chat, để user có thể hỏi tiếp sâu hơn về bài báo đó.

**Điểm hay bị hỏi:**
- Hỏi: "Tại sao không chỉ dùng luôn summary trong RSS mà phải crawl nội dung?"
  - Trả lời: RSS summary thường rất ngắn, đôi khi là quảng cáo/teaser. Nếu chỉ dựa vào đó, tóm tắt sẽ nông, không phản ánh nội dung chính.
- Hỏi: "Nếu trang tin đổi cấu trúc HTML, crawler bị lỗi thì sao?"
  - Trả lời: Hệ thống có logging chi tiết. Khi không crawl được nội dung đủ dài, API sẽ trả lỗi rõ ràng. Có thể cải tiến bằng cách hỗ trợ nhiều chiến lược parse hoặc fallback sang RSS summary với cảnh báo.

---

## 8. Luồng tóm tắt tin tức (News Summarization) – Chi tiết kỹ thuật

Đây là phần đã được chỉnh sửa và debug nhiều lần trong quá trình phát triển.

### 6.1. Vấn đề ban đầu

- RSS feed thường chỉ cung cấp **mô tả rất ngắn**, đôi khi kèm đoạn quảng cáo như:
  - “5 Ways to Secure Containers…”
- Một số bài từ The Hacker News trả về content ~ 200–300 ký tự đầu tiên → rất ngắn, không đại diện cả bài.
- Kết quả: khi gọi LLM tóm tắt, hệ thống chỉ “đọc” được vài dòng đầu → tóm tắt bị:
  - Hời hợt, giống mẫu cố định
  - Không phản ánh nội dung thực của bài báo

### 6.2. Hướng giải quyết

1. **Tăng chất lượng việc lấy nội dung bài báo**:
   - Hàm `NewsFetcher.fetch_article_content(url)` được viết lại để:
     - Dùng `requests` tải HTML
     - Dùng `BeautifulSoup` để:
       - Loại bỏ các thẻ không liên quan (header, footer, nav, sidebar, ads,…)
       - Tìm vùng `article`, `main` hoặc container nội dung chính
       - Duyệt qua các thẻ `p`, `div` chứa text dài
       - Ghép lại thành một chuỗi văn bản tương đối sạch
     - Loại bỏ các dòng quá ngắn hoặc trùng lặp
     - Giới hạn độ dài tối đa (ví dụ 10k–15k ký tự) để không bị quá dài

2. **Phân biệt snippet quảng cáo vs nội dung thật**:
   - Xây dựng danh sách các pattern quảng cáo (promo snippet)
   - Viết hàm `is_placeholder_snippet(text)` để nhận diện nội dung kiểu quảng cáo container-security → nếu phát hiện, bỏ qua đoạn này

3. **Kiểm soát chất lượng nội dung trước khi gọi LLM**:
   - Đo word count của nội dung đã crawl:
     - Nếu số từ quá ít (ví dụ < 30–50 từ) → coi là không đủ tốt để tóm tắt
     - Thử crawl lại hoặc báo lỗi rõ ràng

4. **Thiết kế prompt tóm tắt tự nhiên hơn**:
   - Thay vì template cứng (Overview / Key Findings / Impact / Defensive actions) dễ tạo cảm giác “scripted”
   - Chuyển sang prompt dạng kể chuyện:
     - Giải thích: bài báo nói về gì, bối cảnh, kỹ thuật chính
     - Trình bày ngắn gọn nhưng có chiều sâu, phù hợp người làm an ninh/công nghệ
     - Gợi ý vài khuyến nghị hoặc điểm cần lưu ý

5. **Cấu trúc fallback rõ ràng**:
   - Thứ tự ưu tiên:
     1. Tóm tắt bằng LLM dựa trên full content (nếu lấy được)
     2. Nếu LLM lỗi → dùng `build_structured_brief` để tự tóm tắt dựa trên tách câu
     3. Nếu vẫn không đủ dữ liệu → dùng `build_article_summary` (dùng metadata + những dòng đầu tiên)

### 6.3. Luồng cụ thể khi người dùng bấm “Tóm tắt bài báo”

1. User bấm nút trong UI → `UI/src/user/main.js` gọi API `/api/news/summarize/<article_id>`.
2. Backend (`run_user_web.py`):
   - Tìm bài báo trong DB (title, url, content hiện tại)
   - Nếu `content` rỗng hoặc quá ngắn → gọi `NewsFetcher.fetch_article_content` để lấy lại
   - Chạy qua các bước lọc snippet, đo length, tách câu
   - Gửi nội dung đã xử lý vào LLM (`pipeline._default_model.complete(prompt=...)`)
   - Nhận kết quả, trả về cho UI
   - Ghi log để có thể debug sau này

3. UI thêm 2 message mới vào chat:
   - Một message dạng “Yêu cầu tóm tắt bài báo …”
   - Một message là phần tóm tắt do LLM sinh ra

---

## 9. Phân công công việc giữa các thành viên

Giả sử nhóm gồm 3 thành viên: **Nam**, **Hà**, **Huy** (có thể điều chỉnh tên/role cho đúng với thực tế).

### 7.1. Nam – Backend & Frontend Admin/User

- Thiết kế & code:
  - `run_admin_web.py`, `run_user_web.py`
  - Các API cho chat, tài liệu, tin tức, báo cáo
- Xây dựng Admin UI:
   - `UI/admin_index.html`, `UI/src/admin/main.js`, `UI/admin_styles.css`
  - Dashboard, thống kê, bảng tài liệu pending, modal phê duyệt,…
- Tham gia xây dựng User UI:
  - Kết nối UI với API chat, tài liệu, tin tức

### 7.2. Hà – RAG Pipeline & Xử lý tài liệu

- Thiết kế kiến trúc RAG:
  - `rag_chatbot/core/ingestion/*`
  - `rag_chatbot/core/embedding/*`
  - `rag_chatbot/core/vector_store/*`
  - `rag_chatbot/core/engine/*`, `retriever.py`
- Thiết kế prompt cho QA, query generation, selection:
  - `rag_chatbot/core/prompt/*.py`
- Xử lý format tài liệu:
  - Hỗ trợ nhiều loại file (PDF, DOCX, TXT,…)
  - Chia chunk, gắn metadata, đảm bảo truy vấn hiệu quả

### 7.3. Huy – LLM, Tin tức & Triển khai

- Tích hợp LLM provider:
  - Thiết kế wrapper ở `core/model/model.py`
  - Cấu hình Gemini, OpenRouter, Ollama bằng biến môi trường
- Phát triển tính năng tin tức kỹ thuật:
  - `rag_chatbot/workers/news_fetcher.py`
  - Các endpoint tóm tắt tin tức trong `run_user_web.py`
  - Debug lỗi tóm tắt (RSS snippet, placeholder, LLM provider mismatch)
- Triển khai & môi trường:
  - `Dockerfile`, `docker-compose.yml`, `Makefile`
  - Cấu hình chạy trên server (vd: AWS) và tối ưu hoá hiệu năng

---

## 10. Hướng phát triển tương lai

1. **Bổ sung phân quyền chi tiết**:
   - Phân quyền theo phòng ban, dự án, mức độ mật
   - Cho phép quản lý quyền truy cập tài liệu tinh hơn (ACL)

2. **Cải thiện đánh giá chất lượng câu trả lời**:
   - Gắn cơ chế rating (like/dislike) cho từng câu trả lời
   - Thu thập dữ liệu để fine-tune hoặc điều chỉnh prompt

3. **Hỗ trợ thêm nguồn tin tức & kiến thức**:
   - Kết nối thêm các RSS khác, blog kỹ thuật, tài liệu nội bộ dạng wiki

4. **Tối ưu hiệu năng & chi phí**:
   - Cache kết quả embedding và truy vấn
   - Tối ưu kích thước chunk, top-k retrieval
   - Linh hoạt chọn model LLM (nhẹ/nhanh vs mạnh/chất lượng)

5. **Giao diện & trải nghiệm người dùng**:
   - Dark mode, tuỳ chỉnh theme
   - Thêm tính năng highlight đoạn ngữ cảnh trong tài liệu khi trả lời

---

## 11. Một số câu hỏi vấn đáp thường gặp

Phần này liệt kê một số câu hỏi mà giảng viên có thể hỏi trong buổi bảo vệ, kèm theo hướng trả lời gợi ý.

### 11.1. Tại sao lại chọn RAG mà không fine-tune LLM bằng dữ liệu nội bộ?

**Ý giảng viên:** kiểm tra xem nhóm hiểu sự khác nhau giữa RAG và fine-tune hay không.

**Trả lời gợi ý:**
- Fine-tune LLM với dữ liệu nội bộ:
   - Cần rất nhiều dữ liệu nội bộ đã được gán nhãn tốt.
   - Chi phí cao (tính toán + thời gian), khó lặp lại khi dữ liệu thay đổi.
   - Khó kiểm soát: mô hình có thể “học lệch” nếu dữ liệu không cân bằng.
- RAG:
   - Không cần đụng tới quá trình training của mô hình gốc.
   - Chỉ cần index tài liệu → khi có tài liệu mới, ingest lại là xong.
   - Dễ update, dễ rollback khi tài liệu sai.
- Đối với bài toán kiến thức nội bộ, dữ liệu thay đổi liên tục, nên RAG phù hợp hơn.

### 11.2. Làm sao đảm bảo bảo mật dữ liệu nội bộ khi dùng LLM bên thứ ba (Gemini/OpenRouter)?

**Ý giảng viên:** xem nhóm có suy nghĩ về bảo mật/privacy không.

**Trả lời gợi ý:**
- Với môi trường production, có thể:
   - Dùng các provider có cam kết không dùng dữ liệu để training lại (data privacy).
   - Hoặc triển khai LLM nội bộ (Ollama, self-hosted models) trên hạ tầng công ty.
- Hệ thống được thiết kế với lớp wrapper `core/model/model.py`:
   - Cho phép cấu hình dùng provider nội bộ (Ollama) thay vì Gemini/OpenRouter nếu yêu cầu bảo mật cao.
   - Không phụ thuộc cố định vào một provider nào.

### 11.3. Nếu LLM trả lời sai so với tài liệu nội bộ thì sao?

**Ý giảng viên:** kiểm tra độ tin cậy của hệ thống.

**Trả lời gợi ý:**
- Có thể áp dụng một số biện pháp:
   - Thiết kế prompt rõ ràng: "Nếu không chắc chắn dựa trên tài liệu, hãy trả lời là không biết".
   - Giới hạn thông tin: chỉ đưa context từ tài liệu nội bộ, không cho LLM “bịa" thêm kiến thức ngoài.
   - Cho phép người dùng feedback (báo sai) → admin xem lại và điều chỉnh tài liệu hoặc prompt.
- Về lâu dài, có thể thêm cơ chế scoring:
   - Mỗi câu trả lời có confidence score.
   - Nếu thấp, hiển thị cảnh báo hoặc đề nghị người dùng kiểm tra lại tài liệu gốc.

### 11.4. Hệ thống xử lý như thế nào khi có rất nhiều tài liệu và câu hỏi cùng lúc (scalability)?

**Trả lời gợi ý:**
- Về phía vector store:
   - Có thể chuyển từ store đơn giản sang các hệ như FAISS, Milvus, Weaviate,… để tăng tốc độ truy vấn.
- Về phía backend:
   - Tách riêng worker ingestion (index tài liệu) và worker lấy tin tức.
   - Dùng hàng đợi (message queue) nếu cần.
- Về phía LLM:
   - Có thể dùng nhiều instance, load balancing.
   - Hoặc dùng model nhỏ hơn cho các tác vụ không quá phức tạp để tiết kiệm chi phí.

### 11.5. Hạn chế lớn nhất của hệ thống hiện tại là gì?

**Trả lời gợi ý:** (tuỳ nhóm, nhưng có thể nêu một số điểm):
- Chưa có cơ chế đánh giá tự động chất lượng câu trả lời.
- Việc crawl tin tức vẫn phụ thuộc cấu trúc HTML của từng trang, dễ vỡ khi site thay đổi.
- Chưa tối ưu cho deployment lớn (chưa dùng queue, chưa tách service,…).
- Phân quyền tài liệu mới dừng ở mức role cơ bản, chưa chi tiết như ACL.

---

## 12. Kết luận

Đồ án đã xây dựng được một hệ thống **Trợ lý tri thức nội bộ** tương đối hoàn chỉnh:
- Có khả năng ingest tài liệu, lưu trữ dưới dạng vector và truy vấn bằng RAG
- Tích hợp LLM đa nhà cung cấp để sinh câu trả lời tự nhiên
- Cung cấp 2 giao diện rõ ràng cho Admin và User
- Bổ sung tính năng tin tức kỹ thuật với khả năng tóm tắt và giải thích

Phần quan trọng nhất của hệ thống không chỉ nằm ở việc “gọi LLM”, mà ở chỗ:
- Thiết kế pipeline RAG tốt (ingestion + retrieval)
- Làm sạch & chuẩn hoá dữ liệu đầu vào (tài liệu, tin tức)
- Thiết kế prompt hợp lý và cơ chế fallback khi LLM hoặc dữ liệu gặp vấn đề.

Nhờ đó, trợ lý có thể trả lời câu hỏi dựa trên **kiến thức nội bộ** một cách đáng tin cậy, đồng thời giúp người dùng cập nhật tin tức và hiểu sâu hơn về các chủ đề kỹ thuật phức tạp.
