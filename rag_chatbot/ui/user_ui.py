"""
User UI for the Internal Knowledge System
Allows employees to:
- Ask questions to the chatbot
- View citations from source documents
- Report incorrect or missing information
"""
import os
import sys
import time
import uuid
import gradio as gr
from typing import Tuple, List, Dict
from .theme import CSS
from ..pipeline import LocalRAGPipeline
from ..logger import Logger
from ..database import report_manager, chat_history_manager


class UserUI:
    def __init__(
        self,
        pipeline: LocalRAGPipeline,
        logger: Logger,
        host: str = "host.docker.internal",
        avatar_images: list[str] = None,
    ):
        self.pipeline = pipeline
        self.logger = logger
        self.host = host
        self.avatar_images = avatar_images or []
        self.session_id = str(uuid.uuid4())
        self.last_response = {"question": "", "answer": "", "sources": []}
    
    def _format_sources(self, sources: List[Dict]) -> str:
        """Format source citations as markdown"""
        if not sources:
            return ""
        
        citations = "\n\n📚 **Source:**\n\n"
        
        for source in sources:
            filename = source.get('filename', 'Unknown')
            text = source.get('text', 'No content available')
            
            # Clean up the text - remove extra spaces and newlines
            text = ' '.join(text.split())
            
            page = source.get('page', None)
            page_str = f"Trang {page}" if page else ""
            citations += f"- **{filename}** {page_str}\n"
        
        return citations
    
    def _get_response(
        self,
        message: str,
        chatbot: list[list[str, str]],
        progress=gr.Progress(track_tqdm=True),
    ):
        """Get response from RAG pipeline with sources"""
        if not self.pipeline.get_model_name():
            yield (
                "",
                chatbot + [[message, "⚠️ Please wait, initializing the system..."]],
                [],
                gr.update(visible=False)
            )
            return
        
        if not message:
            yield (
                "",
                chatbot + [[None, "⚠️ Please enter your question."]],
                [],
                gr.update(visible=False)
            )
            return
        
        # Get response from pipeline
        console = sys.stdout
        sys.stdout = self.logger
        
        # Show question immediately
        yield (
            "",
            chatbot + [[message, "⏳ Đang tìm kiếm thông tin..."]],
            [],
            gr.update(visible=False)
        )
        
        try:
            response = self.pipeline.query("condense_plus_context", message, chatbot)
            
            # Extract answer and sources
            answer_text = []
            sources = []
            
            for text in response.response_gen:
                answer_text.append(text)
                partial_answer = "".join(answer_text)
                
                yield (
                    "",
                    chatbot + [[message, partial_answer]],
                    [],
                    gr.update(visible=False)
                )
            
            final_answer = "".join(answer_text)
            
            # Extract sources from response
            # APPROACH: Check top nodes and pick the one that best aligns with the answer
            if hasattr(response, 'source_nodes') and len(response.source_nodes) > 0:
                import re
                
                # Extract key terms from the answer (words longer than 3 chars)
                answer_words = set([w.lower() for w in re.findall(r'\w+', final_answer) if len(w) > 3])
                
                # Score each node based on answer alignment
                best_node = None
                best_alignment_score = -1
                
                for node in response.source_nodes[:3]:  # Check top 3 nodes
                    source_text = node.node.text.lower()
                    
                    # Count how many answer words appear in this source
                    alignment_score = sum(1 for word in answer_words if word in source_text)
                    
                    # Tie-breaker: use retriever score
                    retriever_score = node.score if hasattr(node, 'score') else 0
                    combined_score = alignment_score * 10 + retriever_score
                    
                    if combined_score > best_alignment_score:
                        best_alignment_score = combined_score
                        best_node = node
                
                # Fallback to highest retriever score if no good alignment
                if not best_node:
                    best_node = max(response.source_nodes, key=lambda x: x.score if hasattr(x, 'score') else 0)
                
                source_text = best_node.node.text.strip()
                
                # If text is very long, show a reasonable excerpt
                max_length = 400
                if len(source_text) > max_length:
                    excerpt = source_text[:max_length]
                    last_period = excerpt.rfind('.')
                    if last_period > max_length * 0.7:
                        source_text = excerpt[:last_period + 1]
                    else:
                        source_text = excerpt + '...'
                
                metadata = best_node.node.metadata
                sources.append({
                    'text': source_text,
                    'filename': metadata.get('file_name', 'Unknown'),
                    'page': metadata.get('page_label', None),
                    'score': float(best_node.score) if hasattr(best_node, 'score') else 0.0
                })
            
            # Format response with citations
            formatted_answer = final_answer
            if sources:
                formatted_answer += self._format_sources(sources)
            
            # Store in last_response for report functionality
            self.last_response = {
                "question": message,
                "answer": final_answer,
                "sources": sources
            }
            
            # Save to chat history
            chat_history_manager.add_chat(
                session_id=self.session_id,
                question=message,
                answer=final_answer,
                sources=sources,
                user_type="user"
            )
            
            yield (
                "",
                chatbot + [[message, formatted_answer]],
                sources,
                gr.update(visible=True)
            )
            
        except Exception as e:
            # Check if it's a "no documents" error
            if "No documents loaded" in str(e):
                error_msg = "⚠️ **No documents available yet.**\n\nPlease contact your administrator to upload company documents first."
            else:
                error_msg = f"❌ Error: {str(e)}"
            
            yield (
                "",
                chatbot + [[message, error_msg]],
                [],
                gr.update(visible=False)
            )
        finally:
            sys.stdout = console
    
    def _submit_report(
        self,
        report_type: str,
        report_reason: str,
        user_comment: str
    ) -> str:
        """Submit a user report"""
        if not self.last_response["question"]:
            return "⚠️ No recent conversation to report. Please ask a question first."
        
        if not report_reason:
            return "⚠️ Please provide a reason for the report."
        
        try:
            report_id = report_manager.create_report(
                question=self.last_response["question"],
                answer=self.last_response["answer"],
                report_type=report_type,
                report_reason=report_reason,
                user_comment=user_comment
            )
            
            return f"✅ Thank you! Your report (ID: {report_id}) has been submitted to the admin team."
        except Exception as e:
            return f"❌ Error submitting report: {e}"
    
    def _clear_chat(self):
        """Clear chat history"""
        self.pipeline.clear_conversation()
        self.session_id = str(uuid.uuid4())
        self.last_response = {"question": "", "answer": "", "sources": []}
        return (
            "",
            [],
            [],
            gr.update(visible=False),
            "Chat cleared!"
        )
    
    def build(self) -> gr.Blocks:
        """Build the user interface"""
        with gr.Blocks(title="Internal Knowledge System", theme=gr.themes.Soft(), css=CSS) as user_app:
            gr.Markdown("# 💬 Internal Knowledge System")
            gr.Markdown("Ask questions about company policies, procedures, and documentation")
            
            with gr.Row():
                with gr.Column(scale=2):
                    # Chat interface
                    chatbot = gr.Chatbot(
                        label="Chat",
                        height=500,
                        avatar_images=self.avatar_images if self.avatar_images else None,
                        show_copy_button=True
                    )
                    
                    with gr.Row():
                        message_box = gr.Textbox(
                            label="Your Question",
                            placeholder="e.g., What is the maximum number of vacation days per month?",
                            scale=4
                        )
                        send_btn = gr.Button("Send", variant="primary", scale=1)
                    
                    with gr.Row():
                        clear_btn = gr.Button("🗑️ Clear Chat", size="sm")
                    
                    status_text = gr.Textbox(label="Status", interactive=False, visible=False)
                
                with gr.Column(scale=1):
                    # Report section
                    gr.Markdown("### 📢 Report an Issue")
                    gr.Markdown("If the answer is incorrect or missing information, please let us know!")
                    
                    report_section = gr.Group(visible=False)
                    with report_section:
                        report_type = gr.Radio(
                            choices=["Incorrect Information", "Missing Information", "Unclear Answer"],
                            value="Incorrect Information",
                            label="Issue Type"
                        )
                        
                        report_reason = gr.Textbox(
                            label="What's wrong?",
                            placeholder="Please describe the issue...",
                            lines=3
                        )
                        
                        user_comment = gr.Textbox(
                            label="Additional Comments (Optional)",
                            placeholder="Any other information you'd like to add...",
                            lines=2
                        )
                        
                        submit_report_btn = gr.Button("📤 Submit Report", variant="secondary")
                        report_status = gr.Textbox(label="Report Status", interactive=False)
                    
                    # Sources display (hidden by default)
                    sources_display = gr.JSON(label="📚 Source Documents", visible=False)
            
            # Event handlers
            def send_message(message, history):
                for output in self._get_response(message, history):
                    yield output
            
            send_btn.click(
                fn=send_message,
                inputs=[message_box, chatbot],
                outputs=[message_box, chatbot, sources_display, report_section]
            )
            
            message_box.submit(
                fn=send_message,
                inputs=[message_box, chatbot],
                outputs=[message_box, chatbot, sources_display, report_section]
            )
            
            clear_btn.click(
                fn=self._clear_chat,
                outputs=[message_box, chatbot, sources_display, report_section, status_text]
            )
            
            submit_report_btn.click(
                fn=self._submit_report,
                inputs=[report_type, report_reason, user_comment],
                outputs=[report_status]
            )
        
        return user_app
