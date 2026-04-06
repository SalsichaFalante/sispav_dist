from flask import render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import User
from app import Session # Importa a Session da fábrica
from . import auth_bp # Importa o blueprint


@auth_bp.route('/')
def index():
    return render_template('index.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        db_session = Session()
        user = db_session.query(User).filter_by(email=email).first()
        

        if user and check_password_hash(user.senha, password):
            session['user_id'] = user.id
            session['user_name'] = user.nome
            session['user_email'] = user.email
            session['user_role'] = int(user.role) # Armazena a role na sessão
            flash('Login realizado com sucesso!', 'success')
            db_session.close() # Feche a sessão após ler todos os dados
            return redirect(url_for('main.dashboard_interativo')) 
        else:
            flash('E-mail ou senha inválidos.', 'danger')

        db_session.close() # Garante que a sessão feche em caso de falha

    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Você foi desconectado.', 'info')

    return redirect(url_for('auth.login')) 

@auth_bp.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if request.method == 'POST':
        if request.form['password'] != request.form['confirmPassword']:
            flash('As senhas não coincidem!', 'danger')
            return render_template('cadastro.html')
        
        hashed_password = generate_password_hash(request.form['password'])
        new_user = User(
            nome=request.form['fullName'],
            email=request.form['email'],
            telefone=request.form.get('phone'),
            senha=hashed_password
        )
        db_session = Session()
        try:
            db_session.add(new_user)
            db_session.commit()
            flash('Usuário criado com sucesso! Faça o login.', 'success')
            
            return redirect(url_for('auth.login')) 
        except Exception:
            db_session.rollback()
            flash('Este e-mail já está em uso.', 'danger')
        finally:
            db_session.close()
    return render_template('cadastro.html')