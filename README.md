# Trợ lý tri thức nội bộ (RAG) – Hướng dẫn viết đồ án + tài liệu tham khảo

Repo này là hệ thống trợ lý tri thức nội bộ dựa trên RAG (Retrieval-Augmented Generation): người dùng hỏi đáp dựa trên tài liệu doanh nghiệp, có trích nguồn; admin quản lý tài liệu/người dùng/báo cáo.

## Chạy nhanh (Docker – bản tối ưu)

```powershell
# chạy local
docker compose up -d --build

# xem log
docker compose logs -f --tail 200
```

- Admin: `http://localhost:7860`
- User: `http://localhost:7861`

## Demo MCP “1 server – nhiều client” (dễ dùng khi bảo vệ)

Mục tiêu: chứng minh MCP không chỉ phục vụ UI chat, mà có thể được tái sử dụng bởi nhiều client/app khác nhau.

- **Client A (UI):** vào User UI và chat với prefix `/mcp ...`
- **Client B (CLI):** gọi MCP trực tiếp qua script demo

```powershell
# xem tools có sẵn (tool discovery)
docker exec knowledge-user python scripts/mcp_demo_cli.py list-tools

# gọi tool list_documents
docker exec knowledge-user python scripts/mcp_demo_cli.py list-docs

# gọi tool search_chunks
docker exec knowledge-user python scripts/mcp_demo_cli.py search --query "Nhân sự có những quyền lợi gì" --top-k 5

# xem audit log tool calls (bằng chứng MCP đã chạy)
docker exec knowledge-user python scripts/mcp_demo_cli.py tail-audit --lines 10
```

## Demo kịch bản “Document Improvement Agent” (MCP + LLM)

Mục tiêu: AI agent **rà soát 1 tài liệu nội bộ cụ thể**, phát hiện phần thiếu/không rõ, và đề xuất nội dung bổ sung.
Điểm nhấn MCP: agent gọi tool `search_chunks` **có lọc theo filename** để chứng minh “tool hóa” truy xuất tri thức theo giao thức chuẩn.

```powershell
# (1) Xem danh sách tài liệu để lấy document_id
docker exec knowledge-user python scripts/mcp_demo_cli.py list-docs

# (2) Rà soát 1 tài liệu (ví dụ company#1) và sinh báo cáo cải tiến
docker exec -e INTERNAL_SERVICE_TOKEN=dev-internal-token knowledge-user python scripts/mcp_demo_cli.py doc-improve --document-type company --document-id 1 --goal policy --top-k 3

# (3) Bằng chứng MCP tool calls (audit log)
docker exec knowledge-user python scripts/mcp_demo_cli.py tail-audit --lines 30
```

Kết quả được lưu tại:
- `./data/doc_improvements/<improve_id>.md`
- `./data/doc_improvements/<improve_id>.json`

Cấu hình LLM trong `.env`:

```env
# chọn 1 trong 2
LLM_PROVIDER=gemini
GEMINI_API_KEY=...

# hoặc
# LLM_PROVIDER=github
# LLM_TOKEN=...
```

Gợi ý xử lý lỗi quá tải LLM (503/429): chỉnh env
- `LLM_MAX_CONCURRENT_REQUESTS=1` (hoặc 2)
- `LLM_MAX_RETRIES=3` (hoặc 5)

---

# MỤC LỤC (gợi ý đã chỉnh)

Mục tiêu: phần lý thuyết “vừa đủ”, tập trung mô tả đúng những gì nhóm đã triển khai (RAG pipeline, xử lý tài liệu, vector search, UI, triển khai Docker/CI-CD, tối ưu).

## CHƯƠNG 1: GIỚI THIỆU ĐỀ TÀI

### 1.1 Lý do chọn đề tài
- Viết theo bối cảnh: tri thức nội bộ phân tán, khó tìm kiếm; nhu cầu hỏi đáp nhanh.
- Trong repo: mô tả feature từ `UI/user_index.html`, `run_user_web.py`.
- Tham khảo:
  - RAG overview: https://www.pinecone.io/learn/retrieval-augmented-generation/

### 1.2 Mục tiêu
- 1.2.1 Tổng quát: xây dựng trợ lý hỏi đáp dựa tài liệu nội bộ.
- 1.2.2 Cụ thể (nên liệt kê cái làm được): upload tài liệu, index, chat + trích nguồn, phân quyền admin/user, lịch news/summary, deploy Docker.
- Trong repo: `run_admin_web.py`, `run_user_web.py`, `rag_chatbot/pipeline.py`.

### 1.3 Phạm vi
- 1.3.1 Chức năng: user Q&A, admin quản lý tài liệu/người dùng, thống kê/báo cáo.
- 1.3.2 Kỹ thuật: Flask, SQLite, llama-index, sentence-transformers, Chroma-like storage (tuỳ cấu hình), Gemini/GitHub Models.
- 1.3.3 Triển khai: Docker + (tuỳ chọn) EC2 + GitHub Actions.

### 1.4 Phương pháp nghiên cứu
- Dùng phương pháp thiết kế–hiện thực–đánh giá: khảo sát → thiết kế → triển khai → kiểm thử.

### 1.5 Đóng góp
- Nêu rõ đóng góp kỹ thuật: tích hợp RAG, cache embeddings, cơ chế retry/limit khi LLM quá tải, tối ưu Docker.
- Trong repo: `rag_chatbot/utils/llm_resilience.py`, `Dockerfile`, `docker-compose.prod.yml`.

### 1.6 Cấu trúc luận văn
- Tóm tắt nội dung từng chương 3–5 dòng.

## CHƯƠNG 2: CƠ SỞ LÝ THUYẾT VÀ CÔNG NGHỆ LIÊN QUAN (viết gọn)

### 2.1 Tổng quan hệ thống trợ lý tri thức nội bộ
- Khái niệm, ứng dụng (intranet search, policy Q&A).
- Thách thức: dữ liệu không cấu trúc, hallucination, cập nhật tài liệu, quyền truy cập.

### 2.2 Kiến trúc RAG
- 2.2.1 Nguyên lý: Retrieve → Augment prompt → Generate.
- 2.2.2 Thành phần: ingestion/chunking, embedding, vector store, retriever, LLM.
- 2.2.3 Ưu/nhược.
- Trong repo: `rag_chatbot/core/ingestion/`, `rag_chatbot/core/embedding/`, `rag_chatbot/core/engine/`.
- Tham khảo:
  - LlamaIndex RAG: https://docs.llamaindex.ai/
  - Survey RAG (tổng quan): https://arxiv.org/abs/2005.11401

### 2.3 Mô hình ngôn ngữ lớn (LLM) + API sử dụng
- Trình bày ngắn: LLM là gì, chat completion.
- 2.3.1 Gemini API
- 2.3.2 GitHub Models (Azure AI Inference)
- Trong repo: `rag_chatbot/core/model/gemini_model.py`, `rag_chatbot/core/model/model.py`.
- Tham khảo:
  - Gemini API docs: https://ai.google.dev/
  - Azure AI Inference SDK: https://learn.microsoft.com/azure/ai-services/openai/ (và Azure AI Inference package docs)

### 2.4 MCP (Model Context Protocol) (chỉ viết phần bạn thật sự dùng)
- Nếu bạn chỉ “định hướng” thì ghi rõ: MCP là hướng tích hợp tool/context; chưa triển khai đầy đủ.
- Tham khảo:
  - MCP (repo): https://github.com/modelcontextprotocol

### 2.5 Vector Database + Embedding
- Giải thích embedding + similarity search + top-k.
- Trong repo: `rag_chatbot/core/vector_store/`, `rag_chatbot/core/embedding/embedding.py`.
- Tham khảo:
  - Chroma docs: https://docs.trychroma.com/
  - SBERT: https://www.sbert.net/

### 2.6 Web + Database
- Flask (REST), SQLite (metadata + auth), frontend (HTML/CSS/JS).
- Trong repo: `run_admin_web.py`, `run_user_web.py`, `rag_chatbot/database.py`, `UI/`.
- Tham khảo:
  - Flask: https://flask.palletsprojects.com/
  - SQLite: https://www.sqlite.org/docs.html

### 2.7 Cloud + Container + CI/CD (chỉ viết đúng phần triển khai)
- Docker, Compose, EC2, GitHub Actions.
- Trong repo: `Dockerfile`, `docker-compose.prod.yml`, `.github/workflows/deploy.yml`, `DEPLOY.md`.
- Tham khảo:
  - Docker Compose: https://docs.docker.com/compose/
  - Gunicorn: https://docs.gunicorn.org/
  - GitHub Actions: https://docs.github.com/actions

---

## CHƯƠNG 3: PHÂN TÍCH VÀ THIẾT KẾ HỆ THỐNG

### 3.1 Yêu cầu hệ thống
- Chức năng: login/signup, upload, Q&A, quản trị.
- Phi chức năng: bảo mật cơ bản, thời gian phản hồi, khả năng mở rộng.

### 3.2 Actor analysis
- User / Admin.

### 3.3 Use Case tổng quan
- Vẽ 1 sơ đồ use case tổng.

### 3.4 Use Case chi tiết (nên chọn 4–6 use case chính)
- Đăng nhập/đăng ký, tải tài liệu, hỏi đáp, quản lý tài liệu, quản lý người dùng, báo cáo.
- Trong repo: route tương ứng trong `run_admin_web.py` và `run_user_web.py`.

### 3.5 Thiết kế kiến trúc tổng thể (không gọi là microservices nếu không tách service thật)
- Trình bày: 2 web service (admin/user), chung DB + data volume.
- Data flow: upload → ingestion → embed → store → retrieve → generate.

### 3.6 Thiết kế dữ liệu
- ERD: users, sessions, documents, user_documents, reports, chat_history…
- Trong repo: `rag_chatbot/database.py`.

### 3.7 Thiết kế giao diện
- Wireframe cho admin/user, luồng login, upload, chat.
- Trong repo: `UI/admin_index.html`, `UI/user_index.html`, các file `.js/.css`.

---

## CHƯƠNG 4: CÀI ĐẶT VÀ TRIỂN KHAI

### 4.1 Môi trường phát triển
- OS, Python 3.10, Docker, biến môi trường.

### 4.2 Các module chính (viết theo đúng code)
- Auth: `rag_chatbot/auth.py`
- Document processing: `rag_chatbot/core/ingestion/`
- RAG pipeline: `rag_chatbot/pipeline.py`
- UI/Backend: `run_admin_web.py`, `run_user_web.py`, `UI/`

### 4.3 Tích hợp LLM
- Mô tả chọn provider (`LLM_PROVIDER`) và flow gọi API.
- Nêu xử lý lỗi quá tải (retry/limit).
- Trong repo: `rag_chatbot/core/model/*`, `rag_chatbot/utils/llm_resilience.py`.

### 4.4 Vector search
- Cách tạo node/chunk, embed, retriever top-k.
- Trong repo: `rag_chatbot/core/engine/`, `rag_chatbot/core/vector_store/`.

### 4.5 Deploy cloud
- Docker optimized, volumes, ports.
- CI/CD: build & push image, server pull & restart.
- Trong repo: `Dockerfile`, `docker-compose.prod.yml`, `.github/workflows/deploy.yml`, `DEPLOY.md`.

### 4.6 Bảo mật và tối ưu
- Auth + role, session token.
- Tối ưu: cache embeddings, giảm image size, gunicorn, retry/limit.

---

## CHƯƠNG 5: KIỂM THỬ VÀ ĐÁNH GIÁ

### 5.1 Kế hoạch kiểm thử
- Chọn test theo chức năng + phi chức năng.

### 5.2 Kiểm thử chức năng
- Đăng nhập, upload, hỏi đáp, admin.

### 5.3 Kiểm thử phi chức năng (trình bày vừa phải)
- Hiệu năng: latency Q&A, thời gian index.
- Bảo mật: kiểm tra phân quyền route, session.
- Mở rộng: nhiều user đồng thời + giới hạn LLM.

### 5.4 Kiểm thử tích hợp
- LLM API (Gemini/GitHub), DB, ingestion.

### 5.5 Đánh giá chất lượng câu trả lời
- Đề xuất tiêu chí: relevance, groundedness/citation, response time.
- Tham khảo:
  - RAG eval overview: https://docs.llamaindex.ai/en/stable/examples/evaluation/

---

## CHƯƠNG 6: KẾT QUẢ VÀ THẢO LUẬN

### 6.1 Kết quả
- Tóm tắt tính năng đã làm, demo screenshot.

### 6.2 So sánh và hạn chế
- So sánh với search truyền thống; hạn chế: phụ thuộc quota LLM, dữ liệu thiếu cấu trúc.

### 6.3 Hướng phát triển
- ACL/permission theo tài liệu, multi-tenant, reranker, cache LLM, queue.

---

## KẾT LUẬN
- Tóm tắt đóng góp + mức độ đạt mục tiêu.

## TÀI LIỆU THAM KHẢO
- Gom link ở trên + chuẩn IEEE/APA.

## PHỤ LỤC
- A: Source code chính (liệt kê các file quan trọng)
- B: Cấu hình hệ thống (`.env` mẫu, compose)
- C: Kết quả kiểm thử
- D: Hướng dẫn cài đặt (`DEPLOY.md`)
- E: Screenshots UI
