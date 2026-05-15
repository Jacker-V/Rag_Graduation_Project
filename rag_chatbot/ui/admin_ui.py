"""
Admin UI for the Internal Knowledge System
Allows administrators to:
- Upload company documents (PDF, DOCX, TXT, Markdown)
- View and manage uploaded documents
- View and resolve user reports
"""
import os
import shutil
import gradio as gr
from datetime import datetime
from pathlib import Path
from typing import List, Tuple
from ..database import document_manager, report_manager
from ..pipeline import LocalRAGPipeline


class AdminUI:
    def __init__(self, pipeline: LocalRAGPipeline, data_dir: str = "data/data"):
        self.pipeline = pipeline
        self.data_dir = os.path.join(os.getcwd(), data_dir)
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
    
    def _upload_documents(self, files: List) -> Tuple[str, str]:
        """Upload multiple documents to the system"""
        if not files:
            return "⚠️ No files selected", self._format_documents_list()
        
        uploaded_count = 0
        uploaded_files = []
        
        for file in files:
            try:
                file_path = file.name
                filename = os.path.basename(file_path)
                file_type = os.path.splitext(filename)[1].lower()
                
                # Check file type
                allowed_types = ['.pdf', '.docx', '.txt', '.md', '.markdown']
                if file_type not in allowed_types:
                    continue
                
                # Copy file to data directory
                dest_path = os.path.join(self.data_dir, filename)
                shutil.copy(file_path, dest_path)
                
                # Get file size
                file_size = os.path.getsize(dest_path)
                
                # Add to database
                doc_id = document_manager.add_document(
                    filename=filename,
                    original_filename=filename,
                    file_type=file_type,
                    file_size=file_size,
                    uploaded_by="admin"
                )
                
                uploaded_files.append(dest_path)
                uploaded_count += 1
                
            except Exception as e:
                print(f"Error uploading {filename}: {e}")
                continue
        
        if uploaded_count > 0:
            # Process documents with RAG pipeline
            try:
                self.pipeline.store_nodes(input_files=uploaded_files)
                self.pipeline.set_chat_mode()
                message = f"✅ Successfully uploaded and processed {uploaded_count} document(s)"
            except Exception as e:
                message = f"⚠️ Uploaded {uploaded_count} document(s) but processing failed: {e}"
        else:
            message = "❌ No valid documents uploaded"
        
        return message, self._format_documents_list()
    
    def _get_documents_list(self) -> List[List]:
        """Get list of all documents for display"""
        documents = document_manager.get_all_documents()
        
        if not documents:
            return []
        
        # Format for display: [ID, Filename, Type, Size, Upload Date]
        doc_list = []
        for doc in documents:
            size_mb = doc['file_size'] / (1024 * 1024)
            doc_list.append([
                doc['id'],
                doc['original_filename'],
                doc['file_type'],
                f"{size_mb:.2f} MB",
                doc['upload_date']
            ])
        
        return doc_list
    
    def _calculate_total_storage(self) -> str:
        """Calculate total storage used by all documents"""
        documents = document_manager.get_all_documents()
        total_bytes = sum(doc['file_size'] for doc in documents)
        total_mb = total_bytes / (1024 * 1024)
        
        if total_mb < 1024:
            return f"{total_mb:.2f} MB"
        else:
            total_gb = total_mb / 1024
            return f"{total_gb:.2f} GB"
    
    def _format_documents_list(self) -> str:
        """Format documents list as text"""
        documents = document_manager.get_all_documents()
        
        if not documents:
            return "No documents uploaded yet."
        
        lines = ["ID | Filename | Type | Size | Upload Date"]
        lines.append("-" * 80)
        
        for doc in documents:
            size_mb = doc['file_size'] / (1024 * 1024)
            lines.append(
                f"{doc['id']} | {doc['original_filename']} | {doc['file_type']} | "
                f"{size_mb:.2f} MB | {doc['upload_date']}"
            )
        
        return "\n".join(lines)
    
    def _delete_document(self, doc_id: str) -> Tuple[str, str]:
        """Delete a document from the system"""
        if not doc_id:
            return "⚠️ Please enter a document ID", self._format_documents_list()
        
        try:
            doc_id_int = int(doc_id)
            doc = document_manager.get_document(doc_id_int)
            
            if not doc:
                return f"❌ Document with ID {doc_id} not found", self._format_documents_list()
            
            # Delete from database
            success = document_manager.delete_document(doc_id_int)
            
            if success:
                # Delete physical file
                file_path = os.path.join(self.data_dir, doc['filename'])
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                # Rebuild RAG index
                remaining_docs = document_manager.get_all_documents()
                if remaining_docs:
                    doc_paths = [os.path.join(self.data_dir, d['filename']) for d in remaining_docs]
                    self.pipeline.reset_documents()
                    self.pipeline.store_nodes(input_files=doc_paths)
                    self.pipeline.set_chat_mode()
                else:
                    self.pipeline.reset_documents()
                    self.pipeline.reset_conversation()
                
                return f"✅ Document {doc['original_filename']} deleted successfully", self._format_documents_list()
            else:
                return f"❌ Failed to delete document", self._format_documents_list()
                
        except ValueError:
            return "❌ Invalid document ID", self._format_documents_list()
        except Exception as e:
            return f"❌ Error: {e}", self._format_documents_list()
    
    def _get_reports_list(self, status_filter: str = "All") -> List[List]:
        """Get list of user reports"""
        if status_filter == "All":
            reports = report_manager.get_all_reports()
        else:
            reports = report_manager.get_all_reports(status=status_filter.lower())
        
        if not reports:
            return []
        
        # Format for display
        report_list = []
        for report in reports:
            report_list.append([
                report['id'],
                report['report_type'],
                report['question'][:50] + "..." if len(report['question']) > 50 else report['question'],
                report['report_reason'][:50] + "..." if report['report_reason'] and len(report['report_reason']) > 50 else report['report_reason'],
                report['created_at'],
                report['status']
            ])
        
        return report_list
    
    def _view_report_details(self, report_id: str) -> str:
        """View full details of a report"""
        if not report_id:
            return "Please enter a report ID"
        
        try:
            report_id_int = int(report_id)
            report = report_manager.get_report(report_id_int)
            
            if not report:
                return f"Report with ID {report_id} not found"
            
            details = f"""
## Report #{report['id']} - {report['status'].upper()}

**Type:** {report['report_type']}

**Question:**
{report['question']}

**Answer:**
{report['answer'] or 'N/A'}

**Reason:**
{report['report_reason'] or 'N/A'}

**User Comment:**
{report['user_comment'] or 'N/A'}

**Created:** {report['created_at']}
"""
            
            if report['status'] == 'resolved':
                details += f"""
**Resolved:** {report['resolved_at']}
**Resolved By:** {report['resolved_by']}
**Resolution Notes:** {report['resolution_notes'] or 'N/A'}
"""
            
            return details
            
        except ValueError:
            return "Invalid report ID"
        except Exception as e:
            return f"Error: {e}"
    
    def _resolve_report(self, report_id: str, resolution_notes: str) -> Tuple[str, List]:
        """Mark a report as resolved"""
        if not report_id:
            return "⚠️ Please enter a report ID", self._get_reports_list()
        
        try:
            report_id_int = int(report_id)
            success = report_manager.resolve_report(
                report_id=report_id_int,
                resolved_by="admin",
                resolution_notes=resolution_notes
            )
            
            if success:
                return f"✅ Report #{report_id} marked as resolved", self._get_reports_list()
            else:
                return f"❌ Failed to resolve report", self._get_reports_list()
                
        except ValueError:
            return "❌ Invalid report ID", self._get_reports_list()
        except Exception as e:
            return f"❌ Error: {e}", self._get_reports_list()
    
    def build(self) -> gr.Blocks:
        """Build the admin interface"""
        with gr.Blocks(
            title="Admin Panel - Internal Knowledge System",
            theme=gr.themes.Soft(
                primary_hue="blue",
                secondary_hue="slate",
            ),
            css="""
                .status-success { color: #10b981 !important; font-weight: 500; }
                .status-error { color: #ef4444 !important; font-weight: 500; }
                .status-warning { color: #f59e0b !important; font-weight: 500; }
                .stat-card { padding: 1rem; border-radius: 0.5rem; background: #f8fafc; margin: 0.5rem 0; }
                .header-title { font-size: 2rem; font-weight: 700; margin-bottom: 0.5rem; }
                .header-subtitle { font-size: 1rem; color: #64748b; margin-bottom: 1.5rem; }
            """
        ) as admin_app:
            # Header
            with gr.Row():
                gr.Markdown(
                    """
                    <div class="header-title">🔐 Admin Panel</div>
                    <div class="header-subtitle">Internal Knowledge System - Manage documents and user feedback</div>
                    """,
                    elem_classes="header"
                )
            
            with gr.Tabs():
                # Document Management Tab
                with gr.Tab("📄 Documents", id="documents"):
                    # Statistics Row
                    with gr.Row():
                        with gr.Column(scale=1):
                            total_docs = gr.Textbox(
                                label="Total Documents",
                                value=str(len(document_manager.get_all_documents())),
                                interactive=False,
                                elem_classes="stat-card"
                            )
                        with gr.Column(scale=1):
                            total_size = gr.Textbox(
                                label="Total Storage",
                                value=self._calculate_total_storage(),
                                interactive=False,
                                elem_classes="stat-card"
                            )
                        with gr.Column(scale=2):
                            gr.Markdown("**Supported formats:** PDF, DOCX, TXT, Markdown (.md)")
                    
                    gr.Markdown("---")
                    
                    # Upload Section
                    gr.Markdown("### 📤 Upload New Documents")
                    
                    with gr.Row():
                        with gr.Column(scale=3):
                            upload_files = gr.File(
                                file_count="multiple",
                                label="Select documents to upload (multiple files supported)",
                                file_types=[".pdf", ".docx", ".txt", ".md", ".markdown"],
                                height=150
                            )
                        with gr.Column(scale=1):
                            upload_btn = gr.Button(
                                "📤 Upload & Process",
                                variant="primary",
                                size="lg",
                                scale=1
                            )
                    
                    upload_status = gr.Markdown(elem_classes="status")
                    
                    gr.Markdown("---")
                    gr.Markdown("### 📋 Current Documents")
                    
                    with gr.Row():
                        refresh_docs_btn = gr.Button("🔄 Refresh List", size="sm")
                    
                    documents_table = gr.Dataframe(
                        headers=["ID", "Filename", "Type", "Size", "Uploaded"],
                        datatype=["number", "str", "str", "str", "str"],
                        label="",
                        interactive=False,
                        value=self._get_documents_list(),
                        wrap=True
                    )
                    
                    gr.Markdown("---")
                    gr.Markdown("### 🗑️ Delete Document")
                    
                    with gr.Row():
                        with gr.Column(scale=3):
                            delete_id = gr.Textbox(
                                label="Enter Document ID from table above",
                                placeholder="e.g., 5"
                            )
                        with gr.Column(scale=1):
                            delete_btn = gr.Button("🗑️ Delete Document", variant="stop", size="lg")
                    
                    delete_status = gr.Markdown(elem_classes="status")
                    
                    # Event handlers for Documents tab
                    def upload_with_stats(files):
                        status, _ = self._upload_documents(files)
                        docs = self._get_documents_list()
                        total = str(len(document_manager.get_all_documents()))
                        storage = self._calculate_total_storage()
                        
                        # Format status with colors
                        if "✅" in status:
                            status = f'<div class="status-success">{status}</div>'
                        elif "❌" in status:
                            status = f'<div class="status-error">{status}</div>'
                        else:
                            status = f'<div class="status-warning">{status}</div>'
                        
                        return status, docs, total, storage
                    
                    def delete_with_stats(doc_id):
                        status, _ = self._delete_document(doc_id)
                        docs = self._get_documents_list()
                        total = str(len(document_manager.get_all_documents()))
                        storage = self._calculate_total_storage()
                        
                        # Format status with colors
                        if "✅" in status:
                            status = f'<div class="status-success">{status}</div>'
                        elif "❌" in status:
                            status = f'<div class="status-error">{status}</div>'
                        else:
                            status = f'<div class="status-warning">{status}</div>'
                        
                        return status, docs, total, storage
                    
                    upload_btn.click(
                        fn=upload_with_stats,
                        inputs=[upload_files],
                        outputs=[upload_status, documents_table, total_docs, total_size]
                    )
                    
                    delete_btn.click(
                        fn=delete_with_stats,
                        inputs=[delete_id],
                        outputs=[delete_status, documents_table, total_docs, total_size]
                    )
                    
                    refresh_docs_btn.click(
                        fn=lambda: self._get_documents_list(),
                        outputs=[documents_table]
                    )
                
                # User Reports Tab
                with gr.Tab("📢 Reports", id="reports"):
                    # Statistics Row
                    with gr.Row():
                        with gr.Column(scale=1):
                            total_reports = gr.Textbox(
                                label="Total Reports",
                                value=str(len(report_manager.get_all_reports())),
                                interactive=False,
                                elem_classes="stat-card"
                            )
                        with gr.Column(scale=1):
                            pending_reports = gr.Textbox(
                                label="Pending",
                                value=str(len(report_manager.get_all_reports(status="pending"))),
                                interactive=False,
                                elem_classes="stat-card"
                            )
                        with gr.Column(scale=1):
                            resolved_reports = gr.Textbox(
                                label="Resolved",
                                value=str(len(report_manager.get_all_reports(status="resolved"))),
                                interactive=False,
                                elem_classes="stat-card"
                            )
                    
                    gr.Markdown("---")
                    gr.Markdown("### 📋 User Feedback & Reports")
                    gr.Markdown("View and manage reports from users about incorrect or missing information")
                    
                    with gr.Row():
                        with gr.Column(scale=2):
                            status_filter = gr.Dropdown(
                                choices=["All", "Pending", "Resolved"],
                                value="All",
                                label="Filter by Status",
                                interactive=True
                            )
                        with gr.Column(scale=1):
                            refresh_reports_btn = gr.Button("🔄 Refresh", size="sm")
                    
                    reports_table = gr.Dataframe(
                        headers=["ID", "Type", "Question", "Reason", "Date", "Status"],
                        datatype=["number", "str", "str", "str", "str", "str"],
                        label="",
                        interactive=False,
                        value=self._get_reports_list(),
                        wrap=True
                    )
                    
                    gr.Markdown("---")
                    gr.Markdown("### 👁️ View Report Details")
                    
                    with gr.Row():
                        with gr.Column(scale=3):
                            view_report_id = gr.Textbox(
                                label="Enter Report ID from table above",
                                placeholder="e.g., 3"
                            )
                        with gr.Column(scale=1):
                            view_btn = gr.Button("👁️ View Details", size="lg")
                    
                    report_details = gr.Markdown(
                        value="Select a report ID and click 'View Details' to see full information",
                        elem_classes="report-details"
                    )
                    
                    gr.Markdown("---")
                    gr.Markdown("### ✅ Resolve Report")
                    
                    with gr.Row():
                        with gr.Column(scale=2):
                            resolve_report_id = gr.Textbox(
                                label="Report ID to Resolve",
                                placeholder="e.g., 3"
                            )
                        with gr.Column(scale=3):
                            resolution_notes = gr.Textbox(
                                label="Resolution Notes (Optional)",
                                placeholder="Describe how this issue was resolved...",
                                lines=2
                            )
                    
                    with gr.Row():
                        resolve_btn = gr.Button("✅ Mark as Resolved", variant="primary", size="lg")
                    
                    resolve_status = gr.Markdown(elem_classes="status")
                    
                    # Event handlers for Reports tab
                    def refresh_reports_with_stats(filter_val):
                        reports = self._get_reports_list(filter_val)
                        total = str(len(report_manager.get_all_reports()))
                        pending = str(len(report_manager.get_all_reports(status="pending")))
                        resolved = str(len(report_manager.get_all_reports(status="resolved")))
                        return reports, total, pending, resolved
                    
                    def resolve_with_stats(report_id, notes):
                        status, reports = self._resolve_report(report_id, notes)
                        total = str(len(report_manager.get_all_reports()))
                        pending = str(len(report_manager.get_all_reports(status="pending")))
                        resolved = str(len(report_manager.get_all_reports(status="resolved")))
                        
                        # Format status with colors
                        if "✅" in status:
                            status = f'<div class="status-success">{status}</div>'
                        elif "❌" in status:
                            status = f'<div class="status-error">{status}</div>'
                        else:
                            status = f'<div class="status-warning">{status}</div>'
                        
                        return status, reports, total, pending, resolved
                    
                    status_filter.change(
                        fn=refresh_reports_with_stats,
                        inputs=[status_filter],
                        outputs=[reports_table, total_reports, pending_reports, resolved_reports]
                    )
                    
                    refresh_reports_btn.click(
                        fn=refresh_reports_with_stats,
                        inputs=[status_filter],
                        outputs=[reports_table, total_reports, pending_reports, resolved_reports]
                    )
                    
                    view_btn.click(
                        fn=self._view_report_details,
                        inputs=[view_report_id],
                        outputs=[report_details]
                    )
                    
                    resolve_btn.click(
                        fn=resolve_with_stats,
                        inputs=[resolve_report_id, resolution_notes],
                        outputs=[resolve_status, reports_table, total_reports, pending_reports, resolved_reports]
                    )
        
        return admin_app
