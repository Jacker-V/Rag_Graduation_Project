"""User Flask app runner.

All routes live under `rag_chatbot.web.blueprints.user` and are wired up via
`rag_chatbot.web.app_factory.create_app`.
"""

from rag_chatbot.web import create_app

# Exposed for WSGI servers (gunicorn)
app = create_app('user')


if __name__ == '__main__':
    print("=" * 60)
    print("Starting User Interface Server")
    print("=" * 60)
    print("URL: http://localhost:7861")
    try:
        print(f"Model: {app.pipeline.get_model_name()}")
    except Exception:
        pass
    print("=" * 60)

    # Start news scheduler (runs at 12 AM and 12 PM)
    # Note: run_immediately=False to avoid rate limiting on server restart
    try:
        from rag_chatbot.workers.news_scheduler import start_news_scheduler
        start_news_scheduler(app.pipeline, run_immediately=False)
        print("✓ News scheduler started (fetches at 12:00 AM and 12:00 PM)")
    except Exception as e:
        print(f"⚠ News scheduler not started: {e}")

    # Start summary scheduler (runs at 12 AM and 12 PM)
    # Note: run_immediately=False to avoid rate limiting on server restart
    try:
        from rag_chatbot.workers.summary_scheduler import start_summary_scheduler
        start_summary_scheduler(app.pipeline, run_immediately=False)
        print("✓ Summary scheduler started (generates at 12:00 AM and 12:00 PM)")
    except Exception as e:
        print(f"⚠ Summary scheduler not started: {e}")

    app.run(host='0.0.0.0', port=7861, debug=False)
