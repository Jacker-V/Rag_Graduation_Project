"""Admin Flask app runner.

All routes live under `rag_chatbot.web.blueprints.admin` and are wired up via
`rag_chatbot.web.app_factory.create_app`.
"""

from rag_chatbot.web import create_app

# Exposed for WSGI servers (gunicorn)
app = create_app('admin')


if __name__ == '__main__':
    print("=" * 60)
    print("Starting Admin Interface Server")
    print("=" * 60)
    print("URL: http://localhost:7860")
    print("=" * 60)
    app.run(host='0.0.0.0', port=7860, debug=False)
