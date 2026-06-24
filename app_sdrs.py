"""
Dashboard SDRs — Streamlit
Lê as planilhas públicas das 5 SDRs via Google Sheets (gviz CSV),
aplica filtros de período, médico e status, e exibe KPIs + tabela.

Para rodar:
    streamlit run app_sdrs.py
"""

import unicodedata
import re

import pandas as pd
import requests
import streamlit as st
from io import StringIO

# ============================================================
# CONFIGURAÇÃO DAS FONTES DE DADOS
# Mesmas planilhas do dashboard HTML.
# ============================================================
FONTES = [
    {"sdr": "Ana Carolina",    "id": "1WSeBMd93J8wHJixDPTEwNKuSSCl9LxQJE2qz1dKUSsY", "sheet": "Externos"},
    {"sdr": "Eduarda",         "id": "1AadoZ5T0KRYd-6awO85be1Y09SZWp6WNaM-v1PgmVS0", "sheet": "Externos"},
    {"sdr": "Caroline Duarte", "id": "163XtQOpDQteXJztercpv1jWeonJKs8ZoxSBNpe2-35g",  "sheet": "Externos"},
    {"sdr": "Paula",           "id": "1toJsC4ehdoGNrtNLvtdwncD7QxRUE9UgPpuXlAQ5JH0", "sheet": "Externos"},
    {"sdr": "Brenda",          "id": "13LjfG0b9zDOoBTUUPzFKmynFm4bKe7TZ05qSWpIUw2s", "sheet": "Externos"},
]

# ============================================================
# UTILITÁRIOS
# ============================================================

def norm(s: str) -> str:
    """Normaliza texto: minúsculas, sem acento, sem espaço duplo."""
    s = str(s).strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s)
    return s


def find_col(columns: list[str], candidates: list[str]) -> int:
    """
    Encontra o índice de uma coluna pelos nomes candidatos.
    Tenta correspondência exata primeiro, depois parcial.
    Retorna -1 se não encontrar.
    """
    normalized = [norm(c) for c in columns]
    # 1ª passagem: correspondência exata
    for cand in candidates:
        for i, col in enumerate(normalized):
            if col == norm(cand):
                return i
    # 2ª passagem: correspondência parcial
    for cand in candidates:
        for i, col in enumerate(normalized):
            if norm(cand) in col:
                return i
    return -1


# ============================================================
# CARREGAMENTO DE DADOS
# ============================================================

@st.cache_data(ttl=300, show_spinner=False)
def fetch_sheet(sdr: str, sheet_id: str, sheet_name: str) -> tuple[pd.DataFrame | None, str | None]:
    """
    Busca os dados de uma planilha pública do Google Sheets via URL gviz CSV.
    Cache de 5 minutos (ttl=300) para não bater no Google a cada filtro.
    Retorna (DataFrame, None) em sucesso ou (None, mensagem_erro) em falha.
    """
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    )
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        return df, None
    except Exception as e:
        return None, str(e)


def process_sheet(df_raw: pd.DataFrame, sdr: str) -> pd.DataFrame:
    """
    Recebe o DataFrame bruto de uma SDR e retorna um DataFrame padronizado com:
    SDR, Nome, Telefone, Data de Entrada, Data da Consulta,
    Médico/BU, Canal, Origem, Status, Agendado (0 ou 1).

    A detecção de colunas é automática por nome. Se falhar, usa posições fixas
    como fallback (mesma lógica do dashboard HTML).
    """
    cols = df_raw.columns.tolist()

    # Detecta cada coluna pelo nome (normalizado)
    idx = {
        "nome":     find_col(cols, ["nome do lead", "nome", "lead"]),
        "telefone": find_col(cols, ["telefone", "whatsapp", "celular"]),
        "entrada":  find_col(cols, ["data de entrada"]),
        "consulta": find_col(cols, ["data da consulta", "data consulta"]),
        "medico":   find_col(cols, ["medico", "médico"]),
        "canal":    find_col(cols, ["canal"]),
        "origem":   find_col(cols, ["origem"]),
        "status":   find_col(cols, ["status"]),
    }

    # Posições de fallback caso os cabeçalhos não sejam detectados
    fallback = {"nome": 0, "telefone": 1, "entrada": 2,
                "consulta": 9, "medico": 10, "canal": 11, "origem": 12, "status": 13}

    def col_name(key: str) -> str | None:
        """Retorna o nome da coluna detectada ou a do fallback."""
        i = idx[key]
        if i >= 0 and i < len(cols):
            return cols[i]
        fb = fallback[key]
        if fb < len(cols):
            return cols[fb]
        return None

    def get_text(key: str) -> pd.Series:
        """Retorna a série de texto de uma coluna, com vazios como string vazia."""
        c = col_name(key)
        if c:
            return df_raw[c].fillna("").astype(str).str.strip()
        return pd.Series([""] * len(df_raw), index=df_raw.index)

    def get_date(key: str) -> pd.Series:
        """Converte uma coluna de data para datetime, tolerando formatos variados."""
        c = col_name(key)
        if c:
            return pd.to_datetime(df_raw[c], dayfirst=True, errors="coerce")
        return pd.Series([pd.NaT] * len(df_raw), index=df_raw.index)

    # Monta o DataFrame padronizado
    result = pd.DataFrame(index=df_raw.index)
    result["SDR"]              = sdr
    result["Nome"]             = get_text("nome")
    result["Telefone"]         = get_text("telefone")
    result["Data de Entrada"]  = get_date("entrada")
    result["Data da Consulta"] = get_date("consulta")
    result["Médico/BU"]        = get_text("medico").replace("", "(Sem médico)")
    result["Canal"]            = get_text("canal").replace("", "(Sem canal)")
    result["Origem"]           = get_text("origem").replace("", "(Sem origem)")
    result["Status"]           = get_text("status").replace("", "(Sem status)")

    # Marca como agendado se status for "Agendado" ou variante "Já agendou"
    status_norm = result["Status"].apply(norm)
    result["Agendado"] = (
        (status_norm == "agendado") |
        status_norm.str.contains("ja agendou", na=False)
    ).astype(int)

    # Remove linhas sem data de entrada válida (não são leads reais)
    result = result.dropna(subset=["Data de Entrada"])

    return result


def load_all_data() -> tuple[pd.DataFrame, list[str]]:
    """
    Carrega e processa todas as planilhas das SDRs.
    Retorna (DataFrame consolidado, lista de erros).
    """
    frames = []
    errors = []

    progress = st.progress(0, text="Iniciando carregamento...")

    for i, fonte in enumerate(FONTES):
        progress.progress(i / len(FONTES), text=f"Carregando {fonte['sdr']}...")

        df_raw, err = fetch_sheet(fonte["sdr"], fonte["id"], fonte["sheet"])

        if err:
            errors.append(f"{fonte['sdr']}: {err}")
        else:
            df_proc = process_sheet(df_raw, fonte["sdr"])
            frames.append(df_proc)

    progress.progress(1.0, text="Concluído.")
    progress.empty()

    if frames:
        return pd.concat(frames, ignore_index=True), errors
    return pd.DataFrame(), errors


# ============================================================
# INTERFACE STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Dashboard SDRs",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Dashboard SDRs")
st.caption("Dados lidos diretamente das planilhas do Google Sheets. Filtros aplicados por Data de Entrada.")

# ------------------------------------------------------------
# Botão de carregamento / atualização
# ------------------------------------------------------------
col_btn, col_info = st.columns([1, 4])

with col_btn:
    carregar = st.button("🔄 Carregar / Atualizar dados", use_container_width=True)

# Carrega ao clicar OU na primeira abertura
if carregar or "dados" not in st.session_state:
    df_all, erros = load_all_data()
    st.session_state["dados"] = df_all
    st.session_state["erros"] = erros

# Para o app se não houver dados ainda
if "dados" not in st.session_state or st.session_state["dados"].empty:
    st.info("Clique em **Carregar / Atualizar dados** para começar.")
    st.stop()

df_all: pd.DataFrame = st.session_state["dados"]

# Exibe erros de carregamento se houver
if st.session_state.get("erros"):
    with st.expander("⚠️ Erros de carregamento"):
        for e in st.session_state["erros"]:
            st.error(e)

with col_info:
    st.success(
        f"✅ {len(df_all):,} registros totais carregados de {len(FONTES)} planilhas.".replace(",", ".")
    )

st.divider()

# ------------------------------------------------------------
# FILTROS
# Aplicados em cascata: o período filtra primeiro,
# depois os dropdowns mostram apenas valores existentes.
# ------------------------------------------------------------
st.subheader("Filtros")

f1, f2, f3, f4 = st.columns(4)

with f1:
    data_inicio = st.date_input(
        "Data de início",
        value=pd.Timestamp("2026-06-01").date(),
        format="DD/MM/YYYY",
    )

with f2:
    data_fim = st.date_input(
        "Data de fim",
        value=pd.Timestamp("2026-06-30").date(),
        format="DD/MM/YYYY",
    )

# Aplica filtro de período para popular os dropdowns com valores reais
mask_periodo = (
    (df_all["Data de Entrada"] >= pd.Timestamp(data_inicio)) &
    (df_all["Data de Entrada"] <= pd.Timestamp(data_fim) + pd.Timedelta(hours=23, minutes=59, seconds=59))
)
df_periodo = df_all[mask_periodo]

with f3:
    opcoes_medico = ["Todos"] + sorted(df_periodo["Médico/BU"].dropna().unique().tolist())
    medico_sel = st.selectbox("Médico/BU", opcoes_medico)

with f4:
    opcoes_status = ["Todos"] + sorted(df_periodo["Status"].dropna().unique().tolist())
    status_sel = st.selectbox("Status", opcoes_status)

# Aplica os filtros de médico e status sobre o período já filtrado
df_filtrado = df_periodo.copy()

if medico_sel != "Todos":
    df_filtrado = df_filtrado[df_filtrado["Médico/BU"] == medico_sel]

if status_sel != "Todos":
    df_filtrado = df_filtrado[df_filtrado["Status"] == status_sel]

st.divider()

# ------------------------------------------------------------
# KPIs
# ------------------------------------------------------------
total     = len(df_filtrado)
agendados = int(df_filtrado["Agendado"].sum())
conversao = (agendados / total * 100) if total > 0 else 0.0

k1, k2, k3, k4 = st.columns(4)

k1.metric("Leads no período",  f"{total:,}".replace(",", "."))
k2.metric("Agendados",         f"{agendados:,}".replace(",", "."))
k3.metric("Conversão",         f"{conversao:.1f}%")
k4.metric("SDRs com dados",    len(df_filtrado["SDR"].unique()))

st.divider()

# ------------------------------------------------------------
# TABELA DE LEADS
# ------------------------------------------------------------
st.subheader(f"Leads ({total:,})".replace(",", "."))

# Prepara colunas para exibição: formata datas e oculta índice
df_exibir = df_filtrado[[
    "SDR", "Nome", "Telefone",
    "Data de Entrada", "Data da Consulta",
    "Médico/BU", "Canal", "Origem", "Status", "Agendado"
]].copy()

df_exibir["Data de Entrada"]  = df_exibir["Data de Entrada"].dt.strftime("%d/%m/%Y")
df_exibir["Data da Consulta"] = df_exibir["Data da Consulta"].dt.strftime("%d/%m/%Y").fillna("")

st.dataframe(df_exibir, use_container_width=True, hide_index=True)

# ------------------------------------------------------------
# DOWNLOAD CSV
# ------------------------------------------------------------
csv = df_exibir.to_csv(index=False, sep=",", encoding="utf-8-sig")

st.download_button(
    label="⬇️ Baixar tabela em CSV",
    data=csv,
    file_name="leads_filtrados.csv",
    mime="text/csv",
    use_container_width=False,
)

# ------------------------------------------------------------
# RODAPÉ
# ------------------------------------------------------------
st.divider()
st.caption(
    "Filtro aplicado por **Data de Entrada** no período selecionado. "
    "Status 'Agendado' detectado pela coluna Status da planilha de cada SDR."
)
