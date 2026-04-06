import os
from flask import Flask
from sqlalchemy.orm import sessionmaker
from .models import db # Importa a instância do db do models.py

# Configuração da Session Factory para Blueprints
Session = sessionmaker(bind=db)

def create_app():
    app = Flask(__name__)
    app.secret_key = os.urandom(24)

    # Valor contabil em R$
    @app.template_filter('contabel')
    def contabel_filter(valor):
        if valor is None:
            return "R$ 0,00"
        try:
            valor = float(valor)
            # Formato padrão brasileiro 1.234,56
            return f"R$ {valor:,.2f}".replace(",","X").replace(".",",").replace("X",".")
        except:
            return valor

    # Importa e registra o Blueprint de autenticação
    from .auth.routes import auth_bp
    app.register_blueprint(auth_bp)

    # Importa e registra o Blueprint principal
    from .main.routes import main_bp
    app.register_blueprint(main_bp)

    # Importa e registra o Blueprint da API com um prefixo
    from .api.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    return app