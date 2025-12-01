import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import mysql.connector
import os
import csv
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
)


MAILINGS = [
    {
        "id": "seg_quebras_rcs",
        "titulo": "Quebras & Rejeitadas",
        "descricao": "Contas com problemas de contato e execução de estratégias.",
        "dia_recomendado": 0,
    },
    {
        "id": "ter_cpc",
        "titulo": "CPC (Contato Pessoa Certa)",
        "descricao": "Foco em estabelecer conexões efetivas com os responsáveis pelos débitos.",
        "dia_recomendado": 1,
    },
    {
        "id": "qua_nunca_contatados",
        "titulo": "Nunca Contatados",
        "descricao": "Carteiras novas e clientes sem histórico de contato para maximizar alcance.",
        "dia_recomendado": 2,
    },
]

CARTEIRAS = {
    "517": "Itapeva Autos",
    "518": "DivZero",
    "519": "Cedidas",
}

DIA_SEMANA_NOME = {
    0: "Segunda-feira",
    1: "Terça-feira",
    2: "Quarta-feira",
    3: "Quinta-feira",
    4: "Sexta-feira",
    5: "Sábado",
    6: "Domingo",
}

CRED_PATH = r"\\fs01\ITAPEVA ATIVAS\DADOS\SA_Credencials.txt"
DB_CONFIG = None


SQL_QUEBRAS_REJEITADAS = """
WITH
cpc_ultimo AS (
    SELECT
        st.bsc,
        cad.nmcont,
        MAX(his.data_at) AS dt_ultimo_cpc
    FROM cadastros_tb cad
    JOIN hist_tb his ON his.cod_cli = cad.cod_cad
    JOIN stcob_tb st ON st.st = his.ocorr
    WHERE cad.cod_cli IN ({cod_cli})
      AND cad.stcli <> 'INA'
    GROUP BY cad.nmcont
),
acordos_ranked AS (
    SELECT
        a.nmcont,
        a.cod_aco,
        a.data_aco,
        a.data_cad,
        a.vlr_aco,
        a.qtd_p_aco,
        a.staco,
        ROW_NUMBER() OVER (PARTITION BY a.nmcont ORDER BY a.cod_aco DESC) AS rn_aco
    FROM acordos_tb a
    WHERE a.cod_cli IN ({cod_cli})
      AND a.data_cad >= '2025-07-01'
),
acordos_pagos AS (
    SELECT nmcont
    FROM acordos_ranked
    WHERE rn_aco = 1
      AND staco IN ('P','G','A')
),
acordos_ultimos AS (
    SELECT
        aco.nmcont,
        aco.vlr_aco AS UltimoValorAcordado,
        CASE
            WHEN aco.qtd_p_aco = 1 THEN 'AVISTA'
            WHEN aco.qtd_p_aco > 1 THEN 'PARCELADO'
            ELSE NULL
        END AS TipoAcordo,
        DATE_FORMAT(aco.data_cad, '%d-%m-%Y') AS DataCriacaoGecobi,
        CASE aco.staco
            WHEN 'A' THEN 'Em Acordo'
            WHEN 'E' THEN 'Exceção Rejeitada'
            WHEN 'G' THEN 'Pago'
            WHEN 'Q' THEN 'Quebrado'
            WHEN 'P' THEN 'Em Promessa'
            ELSE 'Sem Dados'
        END AS StatusUltimoAcordo,
        aco.staco
    FROM acordos_ranked aco
    WHERE aco.rn_aco = 1
      AND aco.staco IN ('Q','E','P','G','A')
),
acordos_ex AS (
    SELECT
        aco.nmcont
    FROM acordos_ranked aco
    WHERE aco.rn_aco = 1
      AND aco.staco IN ('Q','E')
),
valores AS (
    SELECT
        recc.nmcont,
        recc.cod_cli,
        GROUP_CONCAT(DISTINCT rec.fat_parc ORDER BY rec.fat_parc SEPARATOR ' || ') AS Contratos,
        GROUP_CONCAT(DISTINCT recc.char_5 ORDER BY recc.char_5 SEPARATOR ' || ') AS TipoProduto
    FROM rec_comp_tb recc
    LEFT JOIN receber_tb rec
        ON rec.nmcont = recc.nmcont
       AND rec.cod_cli = recc.cod_cli
    WHERE recc.cod_cli IN ({cod_cli})
      AND rec.fat_parc NOT LIKE '%ENTRADA%'
      AND recc.nmcont NOT IN (SELECT nmcont FROM acordos_pagos)
    GROUP BY recc.nmcont, recc.cod_cli
),
bens AS (
    SELECT
        ben.nmcont,
        ben.cod_cli,
        CONCAT(ben.marca, ' - ', ben.modelo) AS MarcaModelo,
        ben.placa,
        ben.cor,
        CONCAT(ben.anofab, '/', ben.anomodelo) AS AnoFabModelo,
        COUNT(DISTINCT ben.chassi) AS QtdGarantiasUnicas
    FROM bens_tb ben
    WHERE ben.cod_cli IN ({cod_cli})
    GROUP BY ben.nmcont, ben.cod_cli
),
telefones AS (
    SELECT
        cad.cod_cad AS cod_cad,
        cad.nomecli AS nome,
        cad.cpfcnpj AS cpf,
        cad.nmcont AS nmcont,
        cad.cod_cli AS cod_cli,
        MAX(recc.int_2) AS BindingID,
        DATE_FORMAT(nascto, '%d-%m-%Y') AS DataNascimento,
        cad.infoad AS Portfolio,
        CONCAT(dddfone,telefone) AS telefones,
        ROW_NUMBER() OVER (
            PARTITION BY tel.cod_cad
            ORDER BY FIELD(tel.status, 2, 4, 5, 6, 1, 0), tel.status
        ) AS num
    FROM cadastros_tb cad
    JOIN fones_tb tel
        ON tel.cod_cad = cad.cod_cad
    LEFT JOIN rec_comp_tb recc
        ON recc.nmcont = cad.nmcont AND cad.cod_cli = recc.cod_cli
    WHERE cad.cod_cli IN ({cod_cli})
      AND tel.obs NOT LIKE '%Desconhecido%'
      AND tel.obs NOT LIKE '%incorreto%'
      AND (tel.status IN (2, 4, 5, 6, 1)
           OR (tel.obs NOT LIKE '%Descon%' AND tel.obs NOT LIKE '%incorret%'))
      AND cad.stcli <> 'INA'
      AND LENGTH(CONCAT(dddfone, telefone)) >= 8
      AND CONCAT(dddfone, telefone) NOT LIKE '%X%'
      AND int_1 <> 400
    GROUP BY cad.cod_cad, cad.nomecli, cad.cpfcnpj, cad.nmcont, cad.cod_cli,
             nascto, cad.infoad, dddfone, telefone, tel.status
),
telefones_filtrados AS (
    SELECT * FROM telefones WHERE num <= 7
),
telefones_final AS (
    SELECT
        cod_cad, nome, cpf, nmcont, cod_cli, bindingid, datanascimento, portfolio,
        MAX(CASE WHEN num = 1 THEN telefones END) AS Telefone1,
        MAX(CASE WHEN num = 2 THEN telefones END) AS Telefone2,
        MAX(CASE WHEN num = 3 THEN telefones END) AS Telefone3,
        MAX(CASE WHEN num = 4 THEN telefones END) AS Telefone4,
        MAX(CASE WHEN num = 5 THEN telefones END) AS Telefone5,
        MAX(CASE WHEN num = 6 THEN telefones END) AS Telefone6,
        MAX(CASE WHEN num = 7 THEN telefones END) AS Telefone7
    FROM telefones_filtrados
    GROUP BY cod_cad, nome, cpf, nmcont, cod_cli, bindingid, datanascimento, portfolio
)
SELECT
    t.cod_cad,
    t.nome,
    t.cpf,
    t.bindingid,
    t.datanascimento,
    t.portfolio,
    t.Telefone1, t.Telefone2, t.Telefone3, t.Telefone4, t.Telefone5, t.Telefone6, t.Telefone7,
    b.MarcaModelo,
    b.placa,
    b.cor,
    b.AnoFabModelo,
    b.QtdGarantiasUnicas,
    v.Contratos,
    v.TipoProduto,
    a.UltimoValorAcordado,
    a.TipoAcordo,
    a.DataCriacaoGecobi,
    a.StatusUltimoAcordo
FROM telefones_final t
LEFT JOIN bens b
    ON t.nmcont = b.nmcont AND t.cod_cli = b.cod_cli
JOIN valores v
    ON t.nmcont = v.nmcont AND t.cod_cli = v.cod_cli
LEFT JOIN acordos_ultimos a
    ON t.nmcont = a.nmcont
JOIN acordos_ex ex
    ON t.nmcont = ex.nmcont
LEFT JOIN cpc_ultimo cpc
    ON t.nmcont = cpc.nmcont
WHERE t.cod_cli IN ({cod_cli});
"""


SQL_CPC = """
WITH
cpc_ultimo AS (
    SELECT
        st.bsc,
        cad.nmcont,
        MAX(his.data_at) AS dt_ultimo_cpc
    FROM cadastros_tb cad
    JOIN hist_tb his ON his.cod_cli = cad.cod_cad
    JOIN stcob_tb st ON st.st = his.ocorr
    WHERE cad.cod_cli IN ({cod_cli})
      AND cad.stcli <> 'INA'
      AND st.bsc LIKE '%CPC%'
    GROUP BY cad.nmcont
),
acordos_ranked AS (
    SELECT
        a.nmcont,
        a.cod_aco,
        a.data_aco,
        a.data_cad,
        a.vlr_aco,
        a.qtd_p_aco,
        a.staco,
        ROW_NUMBER() OVER (PARTITION BY a.nmcont ORDER BY a.cod_aco DESC) AS rn_aco
    FROM acordos_tb a
    WHERE a.cod_cli IN ({cod_cli})
      AND a.data_cad >= '2025-07-01'
),
acordos_pagos AS (
    SELECT nmcont
    FROM acordos_ranked
    WHERE rn_aco = 1
      AND staco IN ('P','G','A')
),
acordos_ultimos AS (
    SELECT
        aco.nmcont,
        aco.vlr_aco AS UltimoValorAcordado,
        CASE
            WHEN aco.qtd_p_aco = 1 THEN 'AVISTA'
            WHEN aco.qtd_p_aco > 1 THEN 'PARCELADO'
            ELSE NULL
        END AS TipoAcordo,
        DATE_FORMAT(aco.data_cad, '%d-%m-%Y') AS DataCriacaoGecobi,
        CASE aco.staco
            WHEN 'A' THEN 'Em Acordo'
            WHEN 'E' THEN 'Exceção Rejeitada'
            WHEN 'G' THEN 'Pago'
            WHEN 'Q' THEN 'Quebrado'
            WHEN 'P' THEN 'Em Promessa'
            ELSE 'Sem Dados'
        END AS StatusUltimoAcordo,
        aco.staco
    FROM acordos_ranked aco
    WHERE aco.rn_aco = 1
      AND aco.staco IN ('Q','E','P','G','A')
),
valores AS (
    SELECT
        recc.nmcont,
        recc.cod_cli,
        GROUP_CONCAT(DISTINCT rec.fat_parc ORDER BY rec.fat_parc SEPARATOR ' || ') AS Contratos,
        GROUP_CONCAT(DISTINCT recc.char_5 ORDER BY recc.char_5 SEPARATOR ' || ') AS TipoProduto
    FROM rec_comp_tb recc
    LEFT JOIN receber_tb rec
        ON rec.nmcont = recc.nmcont
       AND rec.cod_cli = recc.cod_cli
    WHERE recc.cod_cli IN ({cod_cli})
      AND rec.fat_parc NOT LIKE '%ENTRADA%'
      AND recc.nmcont NOT IN (SELECT nmcont FROM acordos_pagos)
    GROUP BY recc.nmcont, recc.cod_cli
),
bens AS (
    SELECT
        ben.nmcont,
        ben.cod_cli,
        CONCAT(ben.marca, ' - ', ben.modelo) AS MarcaModelo,
        ben.placa,
        ben.cor,
        CONCAT(ben.anofab, '/', ben.anomodelo) AS AnoFabModelo,
        COUNT(DISTINCT ben.chassi) AS QtdGarantiasUnicas
    FROM bens_tb ben
    WHERE ben.cod_cli IN ({cod_cli})
    GROUP BY ben.nmcont, ben.cod_cli
),
telefones AS (
    SELECT
        cad.cod_cad AS cod_cad,
        cad.nomecli AS nome,
        cad.cpfcnpj AS cpf,
        cad.nmcont AS nmcont,
        cad.cod_cli AS cod_cli,
        MAX(recc.int_2) AS BindingID,
        DATE_FORMAT(nascto, '%d-%m-%Y') AS DataNascimento,
        cad.infoad AS Portfolio,
        CONCAT(dddfone,telefone) AS telefones,
        ROW_NUMBER() OVER (
            PARTITION BY tel.cod_cad
            ORDER BY FIELD(tel.status, 2, 4, 5, 6, 1, 0), tel.status
        ) AS num
    FROM cadastros_tb cad
    JOIN fones_tb tel ON tel.cod_cad = cad.cod_cad
    LEFT JOIN rec_comp_tb recc
        ON recc.nmcont = cad.nmcont AND cad.cod_cli = recc.cod_cli
    WHERE cad.cod_cli IN ({cod_cli})
      AND tel.obs NOT LIKE '%Desconhecido%'
      AND tel.obs NOT LIKE '%incorreto%'
      AND (tel.status IN (2, 4, 5, 6, 1)
           OR (tel.obs NOT LIKE '%Descon%' AND tel.obs NOT LIKE '%incorret%'))
      AND cad.stcli <> 'INA'
      AND LENGTH(CONCAT(dddfone, telefone)) >= 8
      AND CONCAT(dddfone, telefone) NOT LIKE '%X%'
      AND int_1 <> 400
    GROUP BY cad.cod_cad, cad.nomecli, cad.cpfcnpj, cad.nmcont, cad.cod_cli,
             nascto, cad.infoad, dddfone, telefone, tel.status
),
telefones_filtrados AS (
    SELECT * FROM telefones WHERE num <= 7
),
telefones_final AS (
    SELECT
        cod_cad, nome, cpf, nmcont, cod_cli, bindingid, datanascimento, portfolio,
        MAX(CASE WHEN num = 1 THEN telefones END) AS Telefone1,
        MAX(CASE WHEN num = 2 THEN telefones END) AS Telefone2,
        MAX(CASE WHEN num = 3 THEN telefones END) AS Telefone3,
        MAX(CASE WHEN num = 4 THEN telefones END) AS Telefone4,
        MAX(CASE WHEN num = 5 THEN telefones END) AS Telefone5,
        MAX(CASE WHEN num = 6 THEN telefones END) AS Telefone6,
        MAX(CASE WHEN num = 7 THEN telefones END) AS Telefone7
    FROM telefones_filtrados
    GROUP BY cod_cad, nome, cpf, nmcont, cod_cli, bindingid, datanascimento, portfolio
)
SELECT
    t.cod_cad,
    t.nome,
    t.cpf,
    t.bindingid,
    t.datanascimento,
    t.portfolio,
    t.Telefone1, t.Telefone2, t.Telefone3, t.Telefone4, t.Telefone5, t.Telefone6, t.Telefone7,
    b.MarcaModelo,
    b.placa,
    b.cor,
    b.AnoFabModelo,
    b.QtdGarantiasUnicas,
    v.Contratos,
    v.TipoProduto,
    a.UltimoValorAcordado,
    a.TipoAcordo,
    a.DataCriacaoGecobi,
    a.StatusUltimoAcordo
FROM telefones_final t
LEFT JOIN bens b
    ON t.nmcont = b.nmcont AND t.cod_cli = b.cod_cli
JOIN valores v
    ON t.nmcont = v.nmcont AND t.cod_cli = v.cod_cli
LEFT JOIN acordos_ultimos a
    ON t.nmcont = a.nmcont
JOIN cpc_ultimo cpc
    ON t.nmcont = cpc.nmcont
WHERE t.cod_cli IN ({cod_cli});
"""


SQL_NUNCA = """
WITH
cpc_ultimo AS (
    SELECT
        st.bsc,
        cad.nmcont,
        MAX(his.data_at) AS dt_ultimo_cpc
    FROM cadastros_tb cad
    JOIN hist_tb his ON his.cod_cli = cad.cod_cad
    JOIN stcob_tb st ON st.st = his.ocorr
    WHERE cad.cod_cli IN ({cod_cli})
      AND cad.stcli <> 'INA'
      AND st.bsc LIKE '%CPC%'
    GROUP BY cad.nmcont
),
acordos_ranked AS (
    SELECT
        a.nmcont,
        a.cod_aco,
        a.data_aco,
        a.data_cad,
        a.vlr_aco,
        a.qtd_p_aco,
        a.staco,
        ROW_NUMBER() OVER (PARTITION BY a.nmcont ORDER BY a.cod_aco DESC) AS rn_aco
    FROM acordos_tb a
    WHERE a.cod_cli IN ({cod_cli})
      AND a.data_cad >= '2025-07-01'
),
acordos_pagos AS (
    SELECT nmcont
    FROM acordos_ranked
    WHERE rn_aco = 1
      AND staco IN ('P','G','A')
),
acordos_ultimos AS (
    SELECT
        aco.nmcont,
        aco.vlr_aco AS UltimoValorAcordado,
        CASE
            WHEN aco.qtd_p_aco = 1 THEN 'AVISTA'
            WHEN aco.qtd_p_aco > 1 THEN 'PARCELADO'
            ELSE NULL
        END AS TipoAcordo,
        DATE_FORMAT(aco.data_cad, '%d-%m-%Y') AS DataCriacaoGecobi,
        CASE aco.staco
            WHEN 'A' THEN 'Em Acordo'
            WHEN 'E' THEN 'Exceção Rejeitada'
            WHEN 'G' THEN 'Pago'
            WHEN 'Q' THEN 'Quebrado'
            WHEN 'P' THEN 'Em Promessa'
            ELSE 'Sem Dados'
        END AS StatusUltimoAcordo,
        aco.staco
    FROM acordos_ranked aco
    WHERE aco.rn_aco = 1
      AND aco.staco IN ('Q','E','P','G','A')
),
valores AS (
    SELECT
        recc.nmcont,
        recc.cod_cli,
        GROUP_CONCAT(DISTINCT rec.fat_parc ORDER BY rec.fat_parc SEPARATOR ' || ') AS Contratos,
        GROUP_CONCAT(DISTINCT recc.char_5 ORDER BY recc.char_5 SEPARATOR ' || ') AS TipoProduto
    FROM rec_comp_tb recc
    LEFT JOIN receber_tb rec
        ON rec.nmcont = recc.nmcont
       AND rec.cod_cli = recc.cod_cli
    WHERE recc.cod_cli IN ({cod_cli})
      AND rec.fat_parc NOT LIKE '%ENTRADA%'
      AND recc.nmcont NOT IN (SELECT nmcont FROM acordos_pagos)
    GROUP BY recc.nmcont, recc.cod_cli
),
bens AS (
    SELECT
        ben.nmcont,
        ben.cod_cli,
        CONCAT(ben.marca, ' - ', ben.modelo) AS MarcaModelo,
        ben.placa,
        ben.cor,
        CONCAT(ben.anofab, '/', ben.anomodelo) AS AnoFabModelo,
        COUNT(DISTINCT ben.chassi) AS QtdGarantiasUnicas
    FROM bens_tb ben
    WHERE ben.cod_cli IN ({cod_cli})
    GROUP BY ben.nmcont, ben.cod_cli
),
telefones AS (
    SELECT
        cad.cod_cad AS cod_cad,
        cad.nomecli AS nome,
        cad.cpfcnpj AS cpf,
        cad.nmcont AS nmcont,
        cad.cod_cli AS cod_cli,
        MAX(recc.int_2) AS BindingID,
        DATE_FORMAT(nascto, '%d-%m-%Y') AS DataNascimento,
        cad.infoad AS Portfolio,
        CONCAT(dddfone,telefone) AS telefones,
        ROW_NUMBER() OVER (
            PARTITION BY tel.cod_cad
            ORDER BY FIELD(tel.status, 2, 4, 5, 6, 1, 0), tel.status
        ) AS num
    FROM cadastros_tb cad
    JOIN fones_tb tel ON tel.cod_cad = cad.cod_cad
    LEFT JOIN rec_comp_tb recc
        ON recc.nmcont = cad.nmcont AND cad.cod_cli = recc.cod_cli
    WHERE cad.cod_cli IN ({cod_cli})
      AND cad.cod_cad NOT IN(
            SELECT h.cod_cli
            FROM hist_tb h
            WHERE h.cod_cli = cad.cod_cad
              AND h.data_at >= CURDATE() - INTERVAL 60 DAY
            GROUP BY h.cod_cli
      )
      AND tel.obs NOT LIKE '%Desconhecido%'
      AND tel.obs NOT LIKE '%incorreto%'
      AND (tel.status IN (2, 4, 5, 6, 1)
           OR (tel.obs NOT LIKE '%Descon%' AND tel.obs NOT LIKE '%incorret%'))
      AND cad.stcli <> 'INA'
      AND LENGTH(CONCAT(dddfone, telefone)) >= 8
      AND CONCAT(dddfone, telefone) NOT LIKE '%X%'
      AND int_1 <> 400
    GROUP BY cad.cod_cad, cad.nomecli, cad.cpfcnpj, cad.nmcont, cad.cod_cli,
             nascto, cad.infoad, dddfone, telefone, tel.status
),
telefones_filtrados AS (
    SELECT * FROM telefones WHERE num <= 7
),
telefones_final AS (
    SELECT
        cod_cad, nome, cpf, nmcont, cod_cli, bindingid, datanascimento, portfolio,
        MAX(CASE WHEN num = 1 THEN telefones END) AS Telefone1,
        MAX(CASE WHEN num = 2 THEN telefones END) AS Telefone2,
        MAX(CASE WHEN num = 3 THEN telefones END) AS Telefone3,
        MAX(CASE WHEN num = 4 THEN telefones END) AS Telefone4,
        MAX(CASE WHEN num = 5 THEN telefones END) AS Telefone5,
        MAX(CASE WHEN num = 6 THEN telefones END) AS Telefone6,
        MAX(CASE WHEN num = 7 THEN telefones END) AS Telefone7
    FROM telefones_filtrados
    GROUP BY cod_cad, nome, cpf, nmcont, cod_cli, bindingid, datanascimento, portfolio
)
SELECT
    t.cod_cad,
    t.nome,
    t.cpf,
    t.bindingid,
    t.datanascimento,
    t.portfolio,
    t.Telefone1, t.Telefone2, t.Telefone3, t.Telefone4, t.Telefone5, t.Telefone6, t.Telefone7,
    b.MarcaModelo,
    b.placa,
    b.cor,
    b.AnoFabModelo,
    b.QtdGarantiasUnicas,
    v.Contratos,
    v.TipoProduto,
    a.UltimoValorAcordado,
    a.TipoAcordo,
    a.DataCriacaoGecobi,
    a.StatusUltimoAcordo
FROM telefones_final t
LEFT JOIN bens b
    ON t.nmcont = b.nmcont AND t.cod_cli = b.cod_cli
JOIN valores v
    ON t.nmcont = v.nmcont AND t.cod_cli = v.cod_cli
LEFT JOIN acordos_ultimos a
    ON t.nmcont = a.nmcont
LEFT JOIN cpc_ultimo cpc
    ON t.nmcont = cpc.nmcont
WHERE t.cod_cli IN ({cod_cli});
"""


def carregar_config_db():
    cfg_raw = {}
    with open(CRED_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if "=" not in line or line.strip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            cfg_raw[key.strip()] = value.strip().strip('"').strip("'")

    return {
        "host": cfg_raw.get("GECOBI_HOST"),
        "user": cfg_raw.get("GECOBI_USER"),
        "password": cfg_raw.get("GECOBI_PASS"),
        "database": cfg_raw.get("GECOBI_DB"),
        "port": int(cfg_raw.get("GECOBI_PORT", 3306)),
    }


def get_db_connection():
    global DB_CONFIG
    if DB_CONFIG is None:
        DB_CONFIG = carregar_config_db()
    return mysql.connector.connect(**DB_CONFIG)


def salvar_csv(mailing_id, carteira_id, colunas, rows):
    """
    Gera o nome do arquivo com prefixo por carteira:
      517 -> AutosPF
      518 -> DivZeroPF
      519 -> CedidasPF

    E sufixo pelo mailing:
      seg_quebras_rcs      -> QuebrasRejeitadas
      ter_cpc              -> CPC
      qua_nunca_contatados -> NuncaContatados

    Ex.: AutosPF_QuebrasRejeitadas_20250101_101500.csv
         DivZeroPF_CPC_20250101_101500.csv
         CedidasPF_NuncaContatados_20250101_101500.csv
    """
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Prefixo por carteira
    prefixos_carteira = {
        "517": "AutosPF",
        "518": "DivZeroPF",
        "519": "CedidasPF",
    }

    # Sufixo por mailing (nome amigável)
    sufixos_mailing = {
        "seg_quebras_rcs": "QuebrasRejeitadas",
        "ter_cpc": "CPC",
        "qua_nunca_contatados": "NuncaContatados",
    }

    base = prefixos_carteira.get(carteira_id, "AutosPF")
    sufixo = sufixos_mailing.get(mailing_id, mailing_id)

    prefixo = f"{base}_{sufixo}"
    caminho = os.path.join(desktop, f"{prefixo}_{timestamp}.csv")

    text_cols = []
    for i, c in enumerate(colunas):
        c_lower = c.lower()
        if (
            "telefone" in c_lower
            or "cpf" in c_lower
            or "binding" in c_lower
            or "contratos" in c_lower
            or "data" in c_lower
            or c_lower.startswith("dt")
        ):
            text_cols.append(i)

    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(colunas)
        for row in rows:
            linha = []
            for i, v in enumerate(row):
                if i in text_cols:
                    linha.append((v))
                else:
                    linha.append("" if v is None else str(v))
            w.writerow(linha)

    return caminho


def _encontrar_campo_usuario(driver, wait):
    """Tenta localizar o campo de usuário por vários seletores mais específicos."""
    xpaths = [
        # fallback mais genérico, mas ainda clicável
        "//input[@type='text' or @type='email']",
    ]
    wait = WebDriverWait(driver, 3)
    for xp in xpaths:
        try:
            elem = wait.until(EC.element_to_be_clickable((By.XPATH, xp)))
            if elem:
                return elem
        except TimeoutException:
            continue
    raise TimeoutException("Não foi possível localizar o campo de usuário na tela de login da OLOS.")


def _encontrar_campo_senha(driver, wait):
    """Tenta localizar o campo de senha por vários seletores mais específicos."""
    xpaths = [
        "//input[@type='password']",
    ]
    wait = WebDriverWait(driver, 3)
    for xp in xpaths:
        try:
            elem = wait.until(EC.element_to_be_clickable((By.XPATH, xp)))
            if elem:
                return elem
        except TimeoutException:
            continue
    raise TimeoutException("Não foi possível localizar o campo de senha na tela de login da OLOS.")


def abrir_e_logar_olos(caminho_csv=None):
    try:
        # Carrega credenciais / URL da OLOS do mesmo TXT do banco
        cfg_raw = {}
        with open(CRED_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if "=" not in line or line.strip().startswith("#"):
                    continue
                key, value = line.split("=", 1)
                cfg_raw[key.strip()] = value.strip().strip('"').strip("'")

        url = cfg_raw.get(
            "OLOS_URL",
            "https://oliveiraantunesadv.oloschannel.com.br/Olos/Login.aspx",
        )
        usuario = cfg_raw.get("OLOS_USER")
        senha = cfg_raw.get("OLOS_PASS")

        # Fallback se não estiver configurado no TXT
        if not usuario or not senha:
            print("[AVISO] OLOS_USER / OLOS_PASS não encontrados no SA_Credencials.txt, usando padrão.")
            usuario = "lucas.b"
            senha = "Lucas.25"

        # Debug básico (sem expor a senha)
        print(f"[DEBUG] OLOS_URL: {url}")
        print(f"[DEBUG] OLOS_USER: {usuario}")
        print(f"[DEBUG] OLOS_PASS len: {len(senha) if senha else 0}")

        chrome_options = Options()
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_experimental_option("detach", True)

        driver = webdriver.Chrome(options=chrome_options)
        wait = WebDriverWait(driver, 20)

        driver.get(url)

        try:
            # Localiza campos de usuário/senha de forma mais robusta
            user_input = _encontrar_campo_usuario(driver, wait)
            pass_input = _encontrar_campo_senha(driver, wait)

            user_input.clear()
            user_input.send_keys(usuario)
            pass_input.clear()
            pass_input.send_keys(senha)

            # Botão de login mais robusto também
            try:
                btn = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' or contains(.,'Entrar') or contains(.,'Login')]"))
                )
            except TimeoutException:
                btn = wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@type='submit' or contains(@value,'Entrar') or contains(@value,'Login')]"))
                )

            driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            driver.execute_script("arguments[0].click();", btn)

        except Exception as e:
            print(f"[ERRO] Falha ao preencher login/senha na OLOS: {e}")
            # Pode já estar logado ou usar SSO, etc.

        # Abrir menu externo
        try:
            wait.until(
                EC.element_to_be_clickable(
                    (By.ID, "ctl00_PageMenu_LinkButtonExternalLink")
                )
            ).click()
        except TimeoutException:
            print("[ERRO] Não encontrou o botão 'LinkButtonExternalLink' após o login.")
            return

        # Painel de customizações
        wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(., 'Painel de Customizações')]")
            )
        ).click()

        # Trocar para a nova aba
        wait.until(lambda d: len(d.window_handles) > 1)
        driver.switch_to.window(driver.window_handles[-1])

        # Import/Export Web
        wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//span[normalize-space()='Import/Export Web']")
            )
        ).click()

        # ImportFiles
        wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//span[normalize-space()='ImportFiles']")
            )
        ).click()

        # Menu "Importar"
        wait.until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "body > header > div.sh-sideleft-menu.ps.ps--theme_default "
                    "> ul > li:nth-child(2) > a > span",
                )
            )
        ).click()

        # Enviar Mailing
        btn_enviar_mailing = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//span[normalize-space()='Enviar Mailing']")
            )
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", btn_enviar_mailing)
        driver.execute_script("arguments[0].click();", btn_enviar_mailing)

        # Se tiver arquivo CSV, faz upload automático
        if caminho_csv:
            input_upload = wait.until(
                EC.presence_of_element_located((By.ID, "file"))
            )
            input_upload.send_keys(caminho_csv)

            btn_enviar_final = wait.until(
                EC.element_to_be_clickable((By.ID, "btn-submit"))
            )
            driver.execute_script(
                "arguments[0].scrollIntoView(true);", btn_enviar_final
            )
            driver.execute_script("arguments[0].click();", btn_enviar_final)

            nome_arquivo = os.path.basename(caminho_csv)

            xpath_checkbox = (
                f"//table[@id='datatable']//input[@type='checkbox' "
                f"and contains(@value, '{nome_arquivo}')]"
            )

            checkbox = wait.until(
                EC.element_to_be_clickable((By.XPATH, xpath_checkbox))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", checkbox)
            driver.execute_script("arguments[0].click();", checkbox)

            btn_importar = wait.until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        "//button[contains(@class, 'btn-move') and "
                        "contains(., 'Enviar para Importação')]",
                    )
                )
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", btn_importar)
            driver.execute_script("arguments[0].click();", btn_importar)

            time.sleep(1)

            btn_confirm = wait.until(
                EC.presence_of_element_located((By.ID, "btn-confirm-move"))
            )
            btn_confirm = wait.until(
                EC.element_to_be_clickable((By.ID, "btn-confirm-move"))
            )

            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView(true);", btn_confirm
                )
                btn_confirm.click()
            except (ElementClickInterceptedException, StaleElementReferenceException):
                try:
                    btn_confirm = driver.find_element(By.ID, "btn-confirm-move")
                    driver.execute_script(
                        "arguments[0].scrollIntoView(true);", btn_confirm
                    )
                    driver.execute_script("arguments[0].click();", btn_confirm)
                except Exception as e:
                    print(f"Não conseguiu clicar no botão 'Enviar': {e}")
    except Exception as e:
        print("Erro no Inicializador")
        print(e)
    finally:
        try:
            driver.close()
        except Exception:
            pass
        


class AgendaMailingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.caminho_mailing = None

        self.title("Agenda Semanal de Cobrança")
        self.configure(bg="#f5f5f5")

        self.geometry("750x460")
        self.resizable(False, False)

        self._configurar_estilos()
        self.mailing_var = tk.StringVar()
        self.carteira_var = tk.StringVar(value="517")

        self._layout()
        self._selecionar_mailing_auto()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configurar_estilos(self):
        style = ttk.Style(self)
        style.theme_use("clam")

    def _layout(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=20, pady=20)

        ttk.Label(
            header,
            text="Agenda Semanal de Cobrança",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            header,
            text=(
                "Instruçoes de uso:\n"
                " Escolher uma carteira e um mailing,\n"
                " após isso, fechar essa janela para seguir com o programa"
            ),
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(5, 5))

        carteira_frame = ttk.Frame(header)
        carteira_frame.pack(anchor="w", pady=(5, 5))

        ttk.Label(
            carteira_frame,
            text="Carteira:",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=(0, 10))

        for cod, nome in CARTEIRAS.items():
            ttk.Radiobutton(
                carteira_frame,
                text=f"{cod} - {nome}",
                value=cod,
                variable=self.carteira_var,
            ).pack(side="left", padx=5)

        card = ttk.Frame(self)
        card.pack(fill="both", expand=True, padx=20)

        left = ttk.Frame(card)
        left.pack(side="left", fill="y", padx=(20, 10))

        ttk.Label(
            left,
            text="Mailings disponíveis:",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        for m in MAILINGS:
            ttk.Radiobutton(
                left,
                text=m["titulo"],
                value=m["id"],
                variable=self.mailing_var,
                command=self._atualizar_desc,
            ).pack(anchor="w", pady=3)

        right = ttk.Frame(card)
        right.pack(side="left", fill="both", expand=True)

        ttk.Label(
            right,
            text="Descrição:",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

        self.lbl_desc = ttk.Label(
            right,
            wraplength=450,
            font=("Segoe UI", 9),
            text="Selecione um mailing à esquerda.",
        )
        self.lbl_desc.pack(anchor="w", pady=5)

        footer = ttk.Frame(self)
        footer.pack(fill="x", padx=20, pady=20)

        ttk.Button(
            footer,
            text="Gerar Mailing",
            command=self.gerar_mailing,
        ).pack(side="right")

    def _selecionar_mailing_auto(self):
        hoje = datetime.today().weekday()
        for m in MAILINGS:
            if m["dia_recomendado"] == hoje:
                self.mailing_var.set(m["id"])
                self._atualizar_desc()

    def _atualizar_desc(self):
        mid = self.mailing_var.get()
        m = next((x for x in MAILINGS if x["id"] == mid), None)
        if m:
            self.lbl_desc.config(text=m["descricao"])

    def gerar_mailing(self):
        mid = self.mailing_var.get()
        cod_cli = self.carteira_var.get()

        if mid == "":
            messagebox.showwarning("Selecione um mailing", "Escolha um mailing.")
            return

        if not cod_cli:
            messagebox.showwarning(
                "Selecione a carteira",
                "Escolha uma carteira (517, 518 ou 519).",
            )
            return

        sql_template = {
            "seg_quebras_rcs": SQL_QUEBRAS_REJEITADAS,
            "ter_cpc": SQL_CPC,
            "qua_nunca_contatados": SQL_NUNCA,
        }.get(mid)

        sql = sql_template.format(cod_cli=cod_cli)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        colunas = [c[0] for c in cur.description]
        conn.close()

        caminho = salvar_csv(mid, cod_cli, colunas, rows)
        self.caminho_mailing = caminho

        messagebox.showinfo(
            "OK",
            f"Mailing gerado!\nCarteira: {cod_cli} - {CARTEIRAS.get(cod_cli, '')}\n\nArquivo salvo em:\n{caminho}",
        )

    def _on_close(self):
        caminho = self.caminho_mailing
        self.destroy()
        abrir_e_logar_olos(caminho)


if __name__ == "__main__":
    app = AgendaMailingApp()
    app.mainloop()
