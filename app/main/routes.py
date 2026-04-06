from flask import render_template, redirect, url_for, session, request, flash
from datetime import datetime
from decimal import Decimal
from sqlalchemy import func, extract
from functools import wraps
from app.models import DefeitoTipo, UF, Avaliador, Bairro, SegmentoPavimento, Avaliacao, RegistroDefeito, Municipio

# Imports locais
from app import Session, db # Importa a fábrica de sessões (com S maiúsculo)
from app.models import DefeitoTipo, UF, Avaliador, Bairro, SegmentoPavimento, Avaliacao, RegistroDefeito
from . import main_bp

# Decoradores de autenticação
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Você precisa estar logado para acessar esta página.', 'info')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Você precisa estar logado para acessar esta página.', 'info')
            return redirect(url_for('auth.login'))
        if session.get('user_role') != 2: # 2 = Admin
            flash('Você não tem permissão para acessar esta página.', 'danger')
            return redirect(url_for('main.dashboard_interativo'))
        return f(*args, **kwargs)
    return decorated_function

@main_bp.route('/avaliar', methods=['GET', 'POST'])
@login_required
@admin_required
def avaliar():
    # Cria uma sessão exclusiva para o banco de dados
    db_session = Session()

    try:
        # Carrega dados para os selects do formulário
        ufs = db_session.query(UF).order_by(UF.nome).all()
        defeito_tipos = db_session.query(DefeitoTipo).order_by(DefeitoTipo.id).all()
        avaliadores = db_session.query(Avaliador).order_by(Avaliador.nome).all()

        if request.method == 'POST':
            try:
                # 1. Captura o ID do segmento (pode vir vazio se for nova via)
                segmento_id_form = request.form.get('segmento_id')
                segmento = None
                
                # --- DECISÃO: VIA EXISTENTE OU NOVA? ---
                if segmento_id_form:
                    # CASO 1: Via Existente (selecionada no mapa)
                    segmento = db_session.query(SegmentoPavimento).filter_by(id=int(segmento_id_form)).first()
                    if not segmento:
                        flash('Erro: Segmento informado não encontrado no banco.', 'danger')
                        return redirect(url_for('main.mapa_avaliacao'))
                else:
                    # CASO 2: Nova Via (precisa validar campos de localização)
                    nome_via = request.form.get('nome_via')
                    municipio_id = request.form.get('municipio_id')
                    bairro_nome = request.form.get('bairro_nome')
                    
                    # Validação EXCLUSIVA para nova via
                    if not nome_via or not municipio_id or not bairro_nome:
                        flash('Para cadastrar uma nova via, Nome, Município e Bairro são obrigatórios.', 'warning')
                        return redirect(url_for('main.mapa_avaliacao'))

                    # Lógica de salvar Bairro e Segmento
                    bairro = db_session.query(Bairro).filter_by(nome=bairro_nome, municipio_id=municipio_id).first()
                    if not bairro:
                        bairro = Bairro(nome=bairro_nome, municipio_id=municipio_id)
                        db_session.add(bairro)
                        db_session.flush()

                    # Cria o novo segmento
                    coords = [
                        request.form.get('lon_inicio'), request.form.get('lat_inicio'),
                        request.form.get('lon_fim'), request.form.get('lat_fim')
                    ]
                    # Cria geometria apenas se coordenadas forem fornecidas
                    geom = None
                    if all(coords):
                        geom = f'LINESTRING({coords[0]} {coords[1]}, {coords[2]} {coords[3]})'

                    segmento = SegmentoPavimento(
                        nome_via=nome_via,
                        de=request.form.get('de'),
                        ate=request.form.get('ate'),
                        bairro_id=bairro.id,
                        geometria=geom
                    )
                    db_session.add(segmento)
                    db_session.flush() # Gera o ID do novo segmento

                # --- PARTE COMUM: SALVAR A AVALIAÇÃO ---
                
                avaliador_id_form = request.form.get('avaliador_id_existente')
                avaliador_final_id = 1 # Valor padrão ou lógica de fallback
                
                # Lógica simplificada para avaliador: se escolheu existente, usa ele.
                if avaliador_id_form:
                    avaliador_final_id = int(avaliador_id_form)
                
                # Captura Data
                data_str = request.form.get('data_avaliacao')
                data_av = datetime.strptime(data_str, '%Y-%m-%d') if data_str else datetime.now()

                # Cálculos de PD e ICP
                total_deducao = 0
                pd_panelas = 0
                pd_remendos = 0
                pd_corrugacao = 0
                
                registros_para_salvar = []

                for tipo in defeito_tipos:
                    p_baixo = request.form.get(f'defeito_{tipo.id}_baixo', 0, type=float)
                    p_medio = request.form.get(f'defeito_{tipo.id}_medio', 0, type=float)
                    p_alto = request.form.get(f'defeito_{tipo.id}_alto', 0, type=float)
                    pd_valor = request.form.get(f'defeito_{tipo.id}_pd', 0, type=float)

                    if p_baixo > 0 or p_medio > 0 or p_alto > 0 or pd_valor > 0:
                        total_deducao += pd_valor
                        
                        nome_upper = tipo.nome.upper()
                        if "PANELA" in nome_upper: pd_panelas = pd_valor
                        elif "REMENDO" in nome_upper: pd_remendos = pd_valor
                        elif "CORRUGAÇÃO" in nome_upper: pd_corrugacao = pd_valor

                        registros_para_salvar.append({
                            'tipo_id': tipo.id,
                            'pb': p_baixo, 'pm': p_medio, 'pa': p_alto, 'pd': pd_valor
                        })

                # Cálculo ICP e M&R
                icp_calculado = max(0, 100 - total_deducao)
                
                mer_resultado = "NF"
                if pd_panelas > 5 or pd_remendos > 6: mer_resultado = "RF"
                elif pd_panelas > 0: mer_resultado = "MC"
                elif pd_corrugacao > 5: mer_resultado = "MP"

                # Salva Avaliação
                nova_avaliacao = Avaliacao(
                    data=data_av,
                    vdm=request.form.get('vdm'),
                    classe_funcional=request.form.get('classe_funcional'),
                    icp_obj=icp_calculado,
                    mer_indicado=mer_resultado,
                    seg_pav_id=segmento.id,
                    avaliador_id=avaliador_final_id
                )
                db_session.add(nova_avaliacao)
                db_session.flush()

                # Salva os defeitos
                for reg in registros_para_salvar:
                    novo_reg = RegistroDefeito(
                        avaliacao_id=nova_avaliacao.id,
                        defeito_tipo_id=reg['tipo_id'],
                        percentual_baixo=reg['pb'],
                        percentual_medio=reg['pm'],
                        percentual_alto=reg['pa'],
                        pontos_dedutiveis=reg['pd']
                    )
                    db_session.add(novo_reg)

                db_session.commit()
                flash(f'Avaliação salva! Via: {segmento.nome_via} | ICP: {icp_calculado} ({mer_resultado})', 'success')
                return redirect(url_for('main.dashboard_interativo'))

            except Exception as e:
                db_session.rollback()
                print(f"Erro no processamento POST: {e}")
                flash(f'Ocorreu um erro ao processar: {str(e)}', 'danger')
                return redirect(url_for('main.mapa_avaliacao'))
        
        # Renderiza a página (GET)
        return render_template('mapa_avaliacao.html', ufs=ufs, defeito_tipos=defeito_tipos, avaliadores=avaliadores)

    finally:
        # Fecha a conexão com o banco ao terminar a requisição
        db_session.close()

# Rota Dashboard
@main_bp.route('/dashboard_interativo')
@login_required
def dashboard_interativo():
    session = Session()
    try:
        # 1. Busca todos os Municípios ordenados por nome
        municipios = session.query(Municipio).order_by(Municipio.nome).all()

        # 2. Busca todos os anos distintos que possuem avaliação (ex: 2021, 2020)
        # O 'extract' tira apenas o ano da data (2021-01-01 -> 2021)

        anos_query = session.query(extract('year', Avaliacao.data)).distinct().order_by(extract('year', Avaliacao.data).desc()).all()
        
        # Converte o resultado [(2021,), (2020,)] para uma lista simples [2021, 2020]
        anos = [int(a[0]) for a in anos_query]

        # Envia essas listas para o HTML popular os <select>
        return render_template('dashboard_interativo.html', municipios=municipios, anos=anos)
    except Exception as e:
        print(f"Erro ao carregar dashboard: {e}")
        flash("Erro ao carregar filtros do dashboard.", "danger")
        return render_template('dashboard_interativo.html', municipios=[], anos=[])
    finally:
        session.close()
        
# Rota Mapa Avaliação (aponta para a mesma função avaliar, mas pode ser usada para clareza)
@main_bp.route('/mapa_avaliacao')
@login_required
@admin_required
def mapa_avaliacao():
    return avaliar()

# Em app/main/routes.py


# ──────────────────────────────────────────────────────────────────────────────
# ANÁLISE ECONÔMICA — Lógica real de cálculo
# Referência metodológica: Zanchetta (2017) / Ramos (2023) — UnB
# ──────────────────────────────────────────────────────────────────────────────

# ── Tabela de parâmetros do modelo (Figura 1 do TCC / planilha VBA) ──

# Custos unitários por M&R (R$/m²) — base TPU DER/SP Set/2022
CUSTO_MR = {
    'NF': 0.00,
    'MP': 15.11,   # Lama asfáltica — 100% da área
    'MC': 228.44,  # Fresagem + CBUQ localizado — 5% da área
    'RF': 167.02,  # Fresagem + CBUQ toda seção — 100% da área
    'RC': 255.98,  # Reconstrução completa — 100% da área
}

# Percentual da área do segmento onde o custo é aplicado
AREA_APLICADA = {
    'NF': 0.00,
    'MP': 1.00,
    'MC': 0.05,
    'RF': 1.00,
    'RC': 1.00,
}

# Fator de Manutenção (MF) para cálculo do IP
MF = {
    'NF': 0.1,
    'MP': 0.2,
    'MC': 0.3,
    'RF': 0.4,
    'RC': 0.5,
}

# Fator de Classificação Funcional (FC)
FC = {
    'Arterial':  1.2,
    'Coletora':  1.1,
    'Local':     1.0,
    'Alimentadora': 1.0,  # alias comum
}

# Fator de Tráfego (TF) baseado em VDM cadastrado
def calcular_tf(vdm_str):
    """Converte string VDM para fator TF conforme tabela do modelo."""
    try:
        vdm = float(str(vdm_str).replace(',', '.').strip()) if vdm_str else 0
    except (ValueError, TypeError):
        vdm = 0
    if vdm < 10:     return 10
    if vdm < 100:    return 10
    if vdm < 500:    return 20
    if vdm < 1000:   return 30
    if vdm < 2000:   return 40
    if vdm < 5000:   return 50
    return 100

# ICP esperado após intervenção (valores de transição do VBA/TCC)
ICP_POS_INTERVENCAO = {
    'NF': None,   # mantém ICP atual
    'MP': 91,
    'MC': 87,
    'RF': 78,
    'RC': 68,
}

# Largura padrão (m) para cálculo de área quando não há dado geométrico
LARGURA_PADRAO = 7.0

# Deterioração anual por faixa de ICP (modelo de desempenho Ramos/Zanchetta)
def deteriorar_icp(icp, anos):
    """Aplica o modelo de deterioração por N anos."""
    for _ in range(anos):
        if icp is None:
            break
        queda = 3 if icp >= 85 else 4
        icp = max(0, icp - queda)
    return icp


def calcular_mer(icp):
    """Determina M&R indicada a partir do ICP (critério do modelo VBA)."""
    if icp is None:
        return 'NF'
    if icp >= 91:
        return 'NF'
    if icp >= 87:
        return 'MP'
    if icp >= 78:
        return 'MC'
    if icp >= 68:
        return 'RF'
    return 'RC'


def calcular_comprimento_segmento(geometria, db_session):
    """Calcula comprimento em metros usando PostGIS ST_Length com geografia."""
    from app import db as engine
    from sqlalchemy import text
    try:
        result = db_session.execute(
            text("SELECT ST_Length(ST_Transform(geometria, 32723)) FROM segmentos_pavimento WHERE id = :id"),
            {'id': geometria}
        ).scalar()
        return float(result) if result else 100.0
    except Exception:
        return 100.0


@main_bp.route('/analise_economica', methods=['GET', 'POST'])
@login_required
def analise_economica():
    db_session = Session()

    municipios = []
    resultados = None
    form_data = {}

    try:
        municipios = db_session.query(Municipio).order_by(Municipio.nome).all()

        if request.method == 'POST':
            # ── 1. Captura de parâmetros do formulário ──
            orcamento_str = request.form.get('orcamento', '0').replace('.', '').replace(',', '.')
            try:
                orcamento = float(orcamento_str)
            except ValueError:
                orcamento = 0.0

            anos_projecao = int(request.form.get('anos_projecao', 0) or 0)
            municipio_id  = request.form.get('municipio_id')

            form_data = {
                'orcamento': request.form.get('orcamento'),
                'anos':      anos_projecao,
                'mun_id':    municipio_id,
            }

            if not municipio_id:
                flash('Selecione um município.', 'warning')
            elif orcamento <= 0:
                flash('Informe um orçamento válido.', 'warning')
            else:
                municipio = db_session.query(Municipio).get(municipio_id)

                # ── 2. Busca todos os segmentos do município com avaliação mais recente ──
                from sqlalchemy import text as sqla_text
                from sqlalchemy.orm import joinedload

                # Subquery: última avaliação por segmento
                subq = (
                    db_session.query(
                        Avaliacao.seg_pav_id,
                        func.max(Avaliacao.data).label('ultima_data')
                    )
                    .group_by(Avaliacao.seg_pav_id)
                    .subquery()
                )

                rows = (
                    db_session.query(SegmentoPavimento, Avaliacao)
                    .join(Bairro, SegmentoPavimento.bairro_id == Bairro.id)
                    .filter(Bairro.municipio_id == municipio_id)
                    .outerjoin(
                        subq,
                        SegmentoPavimento.id == subq.c.seg_pav_id
                    )
                    .outerjoin(
                        Avaliacao,
                        (Avaliacao.seg_pav_id == SegmentoPavimento.id) &
                        (Avaliacao.data == subq.c.ultima_data)
                    )
                    .all()
                )

                if not rows:
                    flash('Nenhum segmento encontrado para este município.', 'warning')
                    return render_template('analise_economica.html',
                                           municipios=municipios,
                                           resultados=None,
                                           form_data=form_data)

                # ── 3. Monta lista de vias com todos os atributos necessários ──
                vias = []
                for seg, av in rows:
                    # Comprimento via PostGIS (em metros)
                    try:
                        comp_m = db_session.execute(
                            sqla_text(
                                "SELECT ST_Length(ST_Transform(geometria, 32723)) "
                                "FROM segmentos_pavimento WHERE id = :id"
                            ),
                            {'id': seg.id}
                        ).scalar()
                        comp_m = float(comp_m) if comp_m else 100.0
                    except Exception:
                        comp_m = 100.0

                    area_m2 = comp_m * LARGURA_PADRAO

                    icp_atual = float(av.icp_obj) if (av and av.icp_obj is not None) else None

                    # Aplica deterioração se horizonte > 0
                    icp_projetado = deteriorar_icp(icp_atual, anos_projecao) if anos_projecao > 0 else icp_atual

                    # M&R indicada para o ICP projetado
                    mer = calcular_mer(icp_projetado)

                    # Classe funcional e fatores
                    classe = (av.classe_funcional or 'Local') if av else 'Local'
                    fc_val = FC.get(classe, 1.0)
                    tf_val = calcular_tf(av.vdm if av else None)
                    mf_val = MF[mer]

                    # Índice de Prioridade — maior = mais urgente
                    if icp_projetado and icp_projetado > 0:
                        ip = (1.0 / icp_projetado) * tf_val * fc_val * mf_val
                    else:
                        ip = 9999.0  # ICP=0 → prioridade máxima

                    # Custo da intervenção
                    custo_unitario = CUSTO_MR[mer]
                    area_efetiva   = area_m2 * AREA_APLICADA[mer]
                    custo_total    = custo_unitario * area_efetiva

                    # ICP após intervenção
                    novo_icp = ICP_POS_INTERVENCAO[mer]
                    if novo_icp is None:
                        novo_icp = icp_projetado  # NF mantém

                    vias.append({
                        'id':              seg.id,
                        'nome':            seg.nome_via or f'Segmento {seg.id}',
                        'bairro':          seg.bairro.nome if seg.bairro else '—',
                        'classe':          classe,
                        'comp_m':          round(comp_m, 1),
                        'area_m2':         round(area_m2, 1),
                        'icp_atual':       icp_atual,
                        'icp_projetado':   round(icp_projetado, 1) if icp_projetado is not None else None,
                        'mer':             mer,
                        'tf':              tf_val,
                        'fc':              fc_val,
                        'mf':              mf_val,
                        'ip':              round(ip, 6),
                        'custo_unitario':  custo_unitario,
                        'area_efetiva':    round(area_efetiva, 1),
                        'custo_intervencao': round(custo_total, 2),
                        'novo_icp':        novo_icp,
                    })

                # ── 4. Ordena por IP decrescente (mais prioritário primeiro) ──
                vias.sort(key=lambda v: v['ip'], reverse=True)

                # ── 5. Simula alocação do orçamento ──
                orcamento_restante  = orcamento
                vias_atendidas      = []
                vias_nao_atendidas  = []

                for via in vias:
                    if via['mer'] == 'NF':
                        # NF: inclui sem custo (não consome orçamento)
                        via['atendida'] = True
                        via['icp_final'] = via['novo_icp']
                        vias_atendidas.append(via)
                    elif via['custo_intervencao'] <= orcamento_restante:
                        orcamento_restante -= via['custo_intervencao']
                        via['atendida'] = True
                        via['icp_final'] = via['novo_icp']
                        vias_atendidas.append(via)
                    else:
                        via['atendida'] = False
                        via['icp_final'] = via['icp_projetado']  # sem intervenção
                        vias_nao_atendidas.append(via)

                todas_vias = vias_atendidas + vias_nao_atendidas

                # ── 6. Estatísticas ──
                total_vias         = len(vias)
                total_com_avaliacao = sum(1 for v in vias if v['icp_atual'] is not None)
                vias_intervencao   = [v for v in vias_atendidas if v['mer'] != 'NF']
                custo_executado    = sum(v['custo_intervencao'] for v in vias_intervencao)
                custo_total_necessario = sum(v['custo_intervencao'] for v in vias if v['mer'] != 'NF')

                # ICP médio antes e depois
                icps_antes  = [v['icp_projetado'] for v in vias if v['icp_projetado'] is not None]
                icps_depois = [v['icp_final'] for v in todas_vias if v['icp_final'] is not None]
                icp_medio_antes  = round(sum(icps_antes) / len(icps_antes), 1)   if icps_antes  else 0
                icp_medio_depois = round(sum(icps_depois) / len(icps_depois), 1) if icps_depois else 0

                # Distribuição M&R antes e depois
                dist_mer_antes  = {'NF': 0, 'MP': 0, 'MC': 0, 'RF': 0, 'RC': 0}
                dist_mer_depois = {'NF': 0, 'MP': 0, 'MC': 0, 'RF': 0, 'RC': 0}

                for v in vias:
                    dist_mer_antes[v['mer']] = dist_mer_antes.get(v['mer'], 0) + 1

                for v in todas_vias:
                    mer_final = calcular_mer(v['icp_final']) if v['icp_final'] is not None else 'NF'
                    dist_mer_depois[mer_final] = dist_mer_depois.get(mer_final, 0) + 1

                resultados = {
                    'municipio_nome':        municipio.nome if municipio else '—',
                    'anos_projecao':         anos_projecao,
                    'orcamento_disponivel':  orcamento,
                    'orcamento_gasto':       round(custo_executado, 2),
                    'orcamento_restante':    round(orcamento - custo_executado, 2),
                    'custo_total_necessario': round(custo_total_necessario, 2),
                    'total_vias':            total_vias,
                    'vias_com_avaliacao':    total_com_avaliacao,
                    'vias_atendidas':        len(vias_intervencao),
                    'icp_medio_antes':       icp_medio_antes,
                    'icp_medio_depois':      icp_medio_depois,
                    'ganho_icp':             round(icp_medio_depois - icp_medio_antes, 1),
                    'dist_mer_antes':        dist_mer_antes,
                    'dist_mer_depois':       dist_mer_depois,
                    'tabela_vias':           todas_vias,  # lista completa ordenada por IP
                }

        return render_template(
            'analise_economica.html',
            municipios=municipios,
            resultados=resultados,
            form_data=form_data,
        )

    except Exception as e:
        import traceback
        print(f"Erro na análise econômica: {traceback.format_exc()}")
        flash(f'Erro ao processar análise: {str(e)}', 'danger')
        return redirect(url_for('main.dashboard_interativo'))
    finally:
        db_session.close()