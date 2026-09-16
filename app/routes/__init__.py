def register_blueprints(app):
    from app.routes.game import game_bp
    from app.routes.admin import admin_bp
    from app.routes.multiplayer import multiplayer_bp
    from app.routes.friends import friends_bp
    from app.routes.analytics import analytics_bp

    app.register_blueprint(game_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(multiplayer_bp)
    app.register_blueprint(friends_bp)
    app.register_blueprint(analytics_bp)
