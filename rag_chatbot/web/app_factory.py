import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from rag_chatbot.auth import AuthManager
from rag_chatbot.pipeline import LocalRAGPipeline


def _find_project_root(start: Path) -> Path:
    """Find repo root by walking up until the UI folder is found."""
    current = start
    for _ in range(10):
        if (current / 'UI').exists():
            return current
        current = current.parent
    return start.parent


def create_app(mode: str = 'user') -> Flask:
    """Create and configure the Flask app.

    mode:
      - 'admin': admin web + admin API
      - 'user': user web + user API
    """
    mode = (mode or 'user').strip().lower()
    if mode not in {'admin', 'user'}:
        raise ValueError("mode must be 'admin' or 'user'")

    load_dotenv(override=True)

    project_root = _find_project_root(Path(__file__).resolve())
    ui_dir = str(project_root / 'UI')
    data_dir = project_root / 'data' / 'data'
    db_path = str(project_root / 'data' / 'knowledge_base.db')
    data_dir.mkdir(parents=True, exist_ok=True)

    # Match existing behavior: static served from UI/ at root URL.
    app = Flask(
        __name__,
        template_folder=ui_dir,
        static_folder=ui_dir,
        static_url_path='',
    )

    behind_proxy = os.environ.get('BEHIND_PROXY', '').strip().lower() in {'1', 'true', 'yes'}
    if behind_proxy:
        # Trust a single reverse proxy hop (Caddy/Nginx) for scheme/host/ip.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
        app.config['PREFERRED_URL_SCHEME'] = 'https'
        app.config['SESSION_COOKIE_SECURE'] = True
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    CORS(app)

    # Determine which LLM to use based on environment.
    llm_provider = os.environ.get('LLM_PROVIDER', '').lower().strip()
    if llm_provider in ('ollama', 'openrouter', 'openai'):
        prefix = '[ADMIN]' if mode == 'admin' else '[USER]'
        print(f"{prefix} Warning: LLM_PROVIDER={llm_provider} is not supported; falling back to GitHub/Gemini")
        llm_provider = ''

    if mode == 'user':
        # Keep HuggingFace offline behavior from the previous user server.
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

    use_gemini = llm_provider == 'gemini' or (not llm_provider and os.environ.get('GEMINI_API_KEY'))

    if use_gemini:
        gemini_api_key = os.environ.get('GEMINI_API_KEY')
        if not gemini_api_key:
            raise ValueError('GEMINI_API_KEY environment variable required for Gemini')
        print('=' * 80)
        print('Using Gemini API')
        print('=' * 80)
        pipeline = LocalRAGPipeline(
            auto_init_docs=(mode == 'user'),
            use_gemini=True,
            gemini_api_key=gemini_api_key,
        )
    else:
        if not os.environ.get('LLM_TOKEN'):
            prefix = '[ADMIN]' if mode == 'admin' else '[USER]'
            print(f"{prefix} Warning: LLM_TOKEN not set; GitHub LLM may fail until configured")
        print('=' * 80)
        print('Using GitHub Models API')
        print('=' * 80)
        os.environ['LLM_PROVIDER'] = 'github'
        pipeline = LocalRAGPipeline(auto_init_docs=(mode == 'user'))

    auth_manager = AuthManager(db_path)

    if mode == 'admin':
        from rag_chatbot.web.blueprints.admin import routes as admin_routes

        admin_routes.init_dependencies(pipeline_instance=pipeline, auth_manager_instance=auth_manager)
        app.register_blueprint(admin_routes.app)
    else:
        from rag_chatbot.web.blueprints.user import routes as user_routes

        user_routes.init_dependencies(pipeline_instance=pipeline, auth_manager_instance=auth_manager)
        app.register_blueprint(user_routes.app)

    # Convenience handles for runners / gunicorn
    app.pipeline = pipeline
    app.auth_manager = auth_manager
    app.web_mode = mode

    return app
