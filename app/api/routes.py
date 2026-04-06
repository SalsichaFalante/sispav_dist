from flask import jsonify, session, request
from sqlalchemy.orm import joinedload
from sqlalchemy import func, desc, extract
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from app.main.routes import login_required
from flask import jsonify, request
import json

# Imports locais
from app import Session, db
from app.models import Avaliacao, SegmentoPavimento, Municipio, Bairro, DefeitoTipo, RegistroDefeito
from . import api_bp


@api_bp.route('/municipios/<int:uf_id>')
def get_municipios(uf_id):
    db_session = Session()
    municipios = db_session.query(Municipio).filter_by(uf_id=uf_id).order_by(Municipio.nome).all()
    db_session.close()
    return jsonify([{'id': m.id, 'nome': m.nome} for m in municipios])

@api_bp.route('/bairros/search')
def search_bairros():
    municipio_id = request.args.get('municipio_id', type=int)
    query = request.args.get('query', type=str, default="")
    
    if not municipio_id:
        return jsonify([])

    db_session = Session()
    search_term = f"%{query}%"
    bairros = db_session.query(Bairro).filter(
        Bairro.municipio_id == municipio_id,
        Bairro.nome.ilike(search_term)
    ).limit(10).all()
    db_session.close()
    return jsonify([{'id': b.id, 'nome': b.nome} for b in bairros])

@api_bp.route('/segmentos')
def get_segmentos():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    db_session = Session()
    try:
        segmentos = db_session.query(SegmentoPavimento).filter(SegmentoPavimento.geometria != None).all()
        features = []
        for segmento in segmentos:
            geom_shapely = to_shape(segmento.geometria)
            feature = {
                'type': 'Feature',
                'geometry': mapping(geom_shapely),
                'properties': {
                    'id': segmento.id,
                    'nome': segmento.nome_via,
                    'de': segmento.de,
                    'ate': segmento.ate
                }
            }
            features.append(feature)
        
        feature_collection = {'type': 'FeatureCollection','features': features}
        return jsonify(feature_collection)
    except Exception as e:
        print(f"Erro ao buscar segmentos para o mapa: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        db_session.close()

@api_bp.route('/segmento/avaliacoes/<int:segmento_id>')
@login_required  # Protege o endpoint
def get_avaliacoes_segmento(segmento_id):
    """
    Retorna uma lista de todas as avaliações anuais para um segmento específico,
    incluindo defeitos, ICP e M&R.
    """
    db_session = Session()
    try:
        # Busca todas as avaliações para este segmento, carregando os defeitos
        avaliacoes = db_session.query(Avaliacao).options(
            joinedload(Avaliacao.defeitos_registrados).joinedload(RegistroDefeito.tipo_defeito)
        ).filter(
            Avaliacao.seg_pav_id == segmento_id
        ).order_by(
            desc(Avaliacao.data) # Mais recentes primeiro
        ).all()

        if not avaliacoes:
            return jsonify([]) # Retorna lista vazia se não houver avaliações

        # Formata os dados para o frontend
        dados_formatados = []
        for aval in avaliacoes:
            defeitos_lista = []
            for reg in aval.defeitos_registrados:
                if reg.tipo_defeito: # Garante que o tipo de defeito existe
                    defeitos_lista.append({
                        'nome': reg.tipo_defeito.nome,
                        'pontos': float(reg.pontos_dedutiveis or 0)
                    })

            dados_formatados.append({
                # Usamos o ano como identificador único
                'ano': aval.data.year,
                # Usa icp_obj (objetivo) conforme seu models.py
                'icp': float(aval.icp_obj) if aval.icp_obj is not None else 'N/A', 
                'mer': aval.mer_indicado or 'N/A',
                'defeitos': defeitos_lista
            })
        
        return jsonify(dados_formatados)

    except Exception as e:
        print(f"Erro ao buscar avaliações do segmento: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        db_session.close()


# -------------------------------------------------------------------------
# NOVA ROTA: DADOS DO DASHBOARD INTERATIVO
# -------------------------------------------------------------------------
# No app/api/routes.py

@api_bp.route('/dashboard-data', methods=['GET'])
def dashboard_data():
    session = Session()
    try:
        municipio_id = request.args.get('municipio_id')
        ano = request.args.get('ano')

        if not municipio_id or not ano:
            return jsonify({'error': 'Parâmetros obrigatórios'}), 400
        
        ano = int(ano)

        # 1. Busca Segmentos + Avaliações (Com Eager Loading para os defeitos para ser rápido)
        # Importante: Precisamos fazer um join para garantir que os defeitos venham na query
        query = session.query(SegmentoPavimento, Avaliacao).outerjoin(
            Avaliacao, 
            (Avaliacao.seg_pav_id == SegmentoPavimento.id) & 
            (extract('year', Avaliacao.data) == ano)
        ).join(Bairro).filter(Bairro.municipio_id == municipio_id)

        resultados = query.all()

        geojson_features = []
        stats_mer = {} 
        total_vias = 0
        total_avaliadas = 0
        soma_icp = 0
        
        for seg, av in resultados:
            total_vias += 1
            
            # --- Prepara a lista de defeitos para o Popup ---
            lista_defeitos = []
            icp_valor = None
            
            if av:
                if av.icp_obj is not None:
                    try: 
                        icp_valor = float(av.icp_obj)
                    except: 
                        icp_valor = 0.0
                
                # Coleta os defeitos desta avaliação (Nome e Pontos)
                # O relacionamento 'defeitos_registrados' deve existir no seu model Avaliacao
                if av.defeitos_registrados:
                    for reg in av.defeitos_registrados:
                        if reg.tipo_defeito and (reg.pontos_dedutiveis or 0) > 0:
                            lista_defeitos.append({
                                'nome': reg.tipo_defeito.nome,
                                'pontos': float(reg.pontos_dedutiveis)
                            })

            # --- GeoJSON ---
            geom_json = None
            if seg.geometria:
                geom_str = session.scalar(func.ST_AsGeoJSON(seg.geometria))
                if geom_str: geom_json = json.loads(geom_str)

            if geom_json:
                feature = {
                    "type": "Feature",
                    "geometry": geom_json,
                    "properties": {
                        "id": seg.id,
                        "nome": seg.nome_via,
                        "bairro": seg.bairro.nome if seg.bairro else "",
                        "icp": icp_valor,
                        "mer": av.mer_indicado if av else "N/A",
                        "data": av.data.strftime('%d/%m/%Y') if av else "-",
                        "defeitos": lista_defeitos # <--- Enviando a lista para o popup
                    }
                }
                geojson_features.append(feature)

            # --- Stats ---
            if av and icp_valor is not None:
                total_avaliadas += 1
                soma_icp += icp_valor
                mer = av.mer_indicado or "N/A"
                stats_mer[mer] = stats_mer.get(mer, 0) + 1

        # 2. Gráficos (Mantivemos a lógica dos defeitos por soma de pontos)
        hist_query = session.query(
            extract('year', Avaliacao.data).label('ano'),
            func.avg(Avaliacao.icp_obj).label('media')
        ).join(SegmentoPavimento).join(Bairro).filter(Bairro.municipio_id == municipio_id).group_by('ano').order_by('ano').all()

        evolucao_data = {
            'labels': [int(row.ano) for row in hist_query],
            'data': [round(row.media, 1) if row.media else 0 for row in hist_query]
        }

        defeitos_query = session.query(
            DefeitoTipo.nome, 
            func.sum(RegistroDefeito.pontos_dedutiveis)
        ).join(RegistroDefeito).join(Avaliacao).join(SegmentoPavimento).join(Bairro).filter(
            Bairro.municipio_id == municipio_id, extract('year', Avaliacao.data) == ano
        ).group_by(DefeitoTipo.nome).order_by(func.sum(RegistroDefeito.pontos_dedutiveis).desc()).all()

        defeitos_data = {
            'labels': [d[0] for d in defeitos_query],
            'data': [float(d[1] or 0) for d in defeitos_query]
        }

        return jsonify({
            'mapa': { "type": "FeatureCollection", "features": geojson_features },
            'kpis': {
                'total_vias': total_vias,
                'avaliadas': total_avaliadas,
                'icp_medio': round(soma_icp / total_avaliadas, 1) if total_avaliadas > 0 else 0
            },
            'graficos': { 'mer': stats_mer, 'evolucao': evolucao_data, 'defeitos': defeitos_data }
        })

    except Exception as e:
        print(f"Erro API: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()