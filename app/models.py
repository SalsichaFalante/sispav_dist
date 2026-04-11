"""
Sistema de Gerenciamento de Avaliações de Pavimento
Database models usando SQLAlchemy

"""
import os
from sqlalchemy import create_engine, Column, String, Integer, Date, ForeignKey, Numeric, UniqueConstraint, text
from flask_login import UserMixin
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from geoalchemy2 import Geometry

# Configuração inicial do banco de dados
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:1234@localhost:5432/sispav')

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
db       = create_engine(DATABASE_URL)
Session  = sessionmaker(bind=db) 
session  = Session()

Base     = declarative_base()

class UF(Base):
    """
    Representa as Unidades Federativas (UFs) do Brasil.
    id :            Identificador único da UF.
    sigla :         Sigla da UF (ex: 'SP').
    nome :          Nome completo da UF (ex: 'São Paulo').
    municipios :    Relacionamento com a tabela Municipio. (cada UF pode ter vários municípios)
    """
    __tablename__  = "uf"
    id             = Column(Integer(), primary_key=True)
    sigla          = Column(String(2), nullable=False, unique=True)
    nome           = Column(String(32), nullable=False)
    municipios     = relationship("Municipio", back_populates="uf", cascade="all, delete-orphan")


class Municipio(Base):
    """
    Representa os Municípios do Brasil.
    id :        Identificador único do município.
    nome :      Nome do município.
    uf_id :     Chave estrangeira referenciando a UF a que pertence.
    uf :        Relacionamento com a tabela UF.
    bairros :   Relacionamento com a tabela Bairro. (cada município pode ter vários bairros)
    """
    __tablename__   = "municipios"
    id              = Column(Integer, primary_key=True)
    nome            = Column(String(256), nullable=False)
    uf_id           = Column(Integer, ForeignKey('uf.id'), nullable=False)
    uf              = relationship("UF", back_populates="municipios")
    bairros         = relationship("Bairro", back_populates="municipio", cascade="all, delete-orphan")

class Bairro(Base):
    """
    Representa os Bairros dentro de um Município.
    id :            Identificador único do bairro.
    nome :          Nome do bairro.
    municipio_id :  Chave estrangeira referenciando o município a que pertence.
    municipio :     Relacionamento com a tabela Municipio.
    segmentos :     Relacionamento com a tabela SegmentoPavimento. (cada bairro pode ter vários segmentos de pavimento)
    """
    __tablename__   = "bairros"
    id              = Column(Integer, primary_key=True)
    nome            = Column(String(128), nullable=False)
    municipio_id    = Column(Integer, ForeignKey('municipios.id'), nullable=False)
    municipio       = relationship("Municipio", back_populates="bairros")
    segmentos       = relationship("SegmentoPavimento", back_populates="bairro", cascade="all, delete-orphan")

class SegmentoPavimento(Base):
    """
    Representa os Segmentos de Pavimento dentro de um Bairro.
    id :            Identificador único do segmento.
    nome_via :      Nome da via do segmento.
    de :            Rua de início do segmento.
    ate :           Rua de término do segmento.
    geometria :     Geometria do segmento (usando GeoAlchemy2).
    bairro_id :     Chave estrangeira referenciando o bairro a que pertence.
    bairro :        Relacionamento com a tabela Bairro.
    avaliacoes :    Relacionamento com a tabela Avaliacao. (cada segmento pode ter várias avaliações)
    """
    __tablename__   = "segmentos_pavimento"
    id              = Column(Integer, primary_key=True)
    nome_via        = Column(String(256), nullable=True)
    de              = Column(String(256), nullable=True)
    ate             = Column(String(256), nullable=True)
    geometria       = Column(Geometry('LINESTRING', srid=4326), nullable=False)
    bairro_id       = Column(Integer, ForeignKey('bairros.id'), nullable=True) # Permitindo nulo por simplicidade
    bairro          = relationship("Bairro", back_populates="segmentos")
    avaliacoes      = relationship("Avaliacao", back_populates="segmento", cascade="all, delete-orphan")

class Avaliador(Base):
    """
    Representa os Avaliadores que realizam as avaliações de pavimento.
    id :            Identificador único do avaliador.
    nome :          Nome do avaliador.
    email :         Email do avaliador (único).
    telefone :      Telefone do avaliador.
    status :        Status do avaliador (ex: 'Ativo', 'Inativo').
    avaliacoes :    Relacionamento com a tabela Avaliacao. (cada avaliador pode ter várias avaliações)
    """
    __tablename__       = "avaliadores"
    id                  = Column(Integer, primary_key=True)
    nome                = Column(String(256), nullable=False)
    email               = Column(String(128), unique=True)
    telefone            = Column(String(128))
    status              = Column(String(32), default='Ativo')
    avaliacoes          = relationship("Avaliacao", back_populates="avaliador")


class Avaliacao(Base):
    """
    Representa as Avaliações de Pavimento realizadas pelos avaliadores.
    id :                    Identificador único da avaliação.
    data :                  Data da avaliação.
    vdm :                   Valor do VDM (Veículos por Dia Médio).
    classe_funcional :      Classe funcional do pavimento (Alimentadora, Coletora, Local).
    seg_pav_id :            Chave estrangeira referenciando o segmento de pavimento avaliado.
    avaliador_id :          Chave estrangeira referenciando o avaliador que realizou a avaliação.
    segmento :              Relacionamento com a tabela SegmentoPavimento.
    avaliador :             Relacionamento com a tabela Avaliador.
    defeitos_registrados :  Relacionamento com a tabela RegistroDefeito. (cada avaliação pode ter vários defeitos registrados)
    """
    __tablename__       = "avaliacoes"
    id                  = Column(Integer, primary_key=True)
    data                = Column(Date, nullable=False)
    vdm                 = Column(String(128))
    classe_funcional    = Column(String(128))
    drenagem            = Column(Numeric(5, 2), nullable=True) # 1 ou 2 (tem, não tem)
    calcada             = Column(Numeric(5, 2), nullable=True) # 1, 2 ou 3 (sim, parcial ou não)
    icp_obj             = Column(Numeric(5, 2), nullable=True) # Pode ser nulo até que o calculo seja feito
    icp_sub             = Column(Numeric(5, 2), nullable=True)
    mer_indicado        = Column(String(32), nullable=True) # RF, RC, NF, MP, MC
    seg_pav_id          = Column(Integer, ForeignKey('segmentos_pavimento.id'), nullable=False)
    avaliador_id        = Column(Integer, ForeignKey('avaliadores.id'), nullable=False)
    segmento            = relationship("SegmentoPavimento", back_populates="avaliacoes")
    avaliador           = relationship("Avaliador", back_populates="avaliacoes")
    defeitos_registrados = relationship("RegistroDefeito", back_populates="avaliacao", cascade="all, delete-orphan")

class DefeitoTipo(Base):
    """
    Representa os Tipos de Defeito que podem ser registrados em uma avaliação.
    id :        Identificador único do tipo de defeito.
    nome :      Nome do tipo de defeito (método dos 11 defeitos).
    """
    __tablename__   = "defeitos_tipo"
    id              = Column(Integer, primary_key=True)
    nome            = Column(String(256), unique=True, nullable=False)

class RegistroDefeito(Base):
    """
    Representa os registros de defeitos específicos associados a uma avaliação.
    id :                    Identificador único do registro de defeito.
    avaliacao_id :          Chave estrangeira referenciando a avaliação a que pertence.
    defeito_tipo_id :       Chave estrangeira referenciando o tipo de defeito.
    percentual_baixo :      Percentual do defeito com severidade baixa.
    percentual_medio :      Percentual do defeito com severidade média.
    percentual_alto :       Percentual do defeito com severidade alta.
    pontos_dedutiveis :     Pontos dedutíveis associados ao defeito.
    avaliacao :             Relacionamento com a tabela Avaliacao (um registro pertence a uma avaliação).
    tipo_defeito :          Relacionamento com a tabela DefeitoTipo (um registro refere-se a um tipo de defeito).

    """
    __tablename__       = "registros_defeitos"
    id                  = Column(Integer, primary_key=True)
    avaliacao_id        = Column(Integer, ForeignKey('avaliacoes.id'), nullable=False)
    defeito_tipo_id     = Column(Integer, ForeignKey('defeitos_tipo.id'), nullable=False)
    percentual_baixo    = Column(Numeric(5, 2), default=0.0, nullable=False)
    percentual_medio    = Column(Numeric(5, 2), default=0.0, nullable=False)
    percentual_alto     = Column(Numeric(5, 2), default=0.0, nullable=False)
    pontos_dedutiveis   = Column(Numeric(5, 2), default=0.0, nullable=True)
    avaliacao           = relationship("Avaliacao", back_populates="defeitos_registrados")
    tipo_defeito        = relationship("DefeitoTipo")
    __table_args__      = (UniqueConstraint('avaliacao_id', 'defeito_tipo_id', name='_avaliacao_defeito_uc'),)

class User(Base, UserMixin):
    """
    Representa os Usuários do sistema para autenticação.
    id :        Identificador único do usuário.
    nome :      Nome do usuário.
    email :     Email do usuário (único).
    telefone :  Telefone do usuário.
    senha :     Senha do usuário (armazenada de forma segura).
    """
    __tablename__   = "users"
    id              = Column(Integer, primary_key=True)
    nome            = Column(String(256), nullable=False)
    email           = Column(String(256), unique=True, nullable=False)
    telefone        = Column(String(20))
    role            = Column(Integer, default=1) # 1 - user , 2 - admin
    senha           = Column(String(256), nullable=False)
  
with db.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
    conn.commit()

Base.metadata.create_all(bind=db)