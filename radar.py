"""Radar de decoração para impressão 3D.

Roda uma vez por dia (GitHub Actions) e grava em dados/:
  - hoje.json             -> o que o painel (index.html) mostra
  - historico/AAAA-MM-DD.json -> foto do dia, usada para achar o que está crescendo

Fontes:
  - Printables: modelos de decoração mais baixados/curtidos nos últimos 7 dias
  - Google (autocompletar): o que as pessoas estão digitando no Brasil
  - Mercado Livre (opcional): buscas em alta, se houver ML_CLIENT_ID/ML_CLIENT_SECRET
  - Telegram (opcional): resumo no celular, se houver TELEGRAM_TOKEN/TELEGRAM_CHAT_ID

Só usa a biblioteca padrão do Python; não precisa de pip install.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DADOS = RAIZ / "dados"
HISTORICO = DADOS / "historico"
FUSO_BR = timezone(timedelta(hours=-3))
UA = "radar-decor-3d/1.0 (+https://github.com)"
DIAS_HISTORICO = 120


# ---------- utilidades ----------

def baixar(url, dados=None, cabecalhos=None, tentativas=3):
    cab = {"User-Agent": UA, "Accept": "application/json"}
    cab.update(cabecalhos or {})
    corpo = dados.encode("utf-8") if isinstance(dados, str) else dados
    for n in range(tentativas):
        try:
            req = urllib.request.Request(url, data=corpo, headers=cab)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - qualquer falha de rede vira nova tentativa
            if n == tentativas - 1:
                raise
            print(f"  falhou ({e}), tentando de novo...")
            time.sleep(3 * (n + 1))


def ler_json(caminho, padrao=None):
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def gravar_json(caminho, obj):
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    Path(caminho).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def historico_anterior(hoje):
    """Fotos dos dias anteriores, da mais recente para a mais antiga."""
    fotos = []
    for arq in sorted(HISTORICO.glob("*.json"), reverse=True):
        if arq.stem < hoje.isoformat():
            foto = ler_json(arq)
            if foto:
                fotos.append(foto)
    return fotos


# ---------- Printables ----------

PRINTABLES_API = "https://api.printables.com/graphql/"
PRINTABLES_QUERY = """
query($cat: ID, $ord: String, $lim: Int) {
  morePrints(categoryId: $cat, ordering: $ord, limit: $lim) {
    items {
      id name slug likesCount downloadCount datePublished
      image { filePath }
      license { abbreviation name }
      tags { name }
      user { publicUsername }
    }
  }
}
"""


def classificar_licenca(abrev):
    """sim = pode vender a peça impressa; nao = proibido (NC); conferir = leia a licença."""
    a = (abrev or "").upper().replace("-", " ").strip()
    if "NC" in a.split():
        return "nao"
    if a in ("CC0", "CC BY", "CC BY SA", "CC BY ND", "PUBLIC DOMAIN"):
        return "sim"
    return "conferir"


PRINTABLES_BUSCA = """
query($q: String!, $lim: Int) {
  searchPrints2(query: $q, limit: $lim, ordering: popular) {
    items {
      id name slug likesCount downloadCount datePublished
      image { filePath }
      license { abbreviation name }
      tags { name }
      user { publicUsername }
    }
  }
}
"""


def consultar_printables(query, variaveis, campo):
    try:
        resp = baixar(PRINTABLES_API, json.dumps({"query": query, "variables": variaveis}),
                      {"Content-Type": "application/json"})
    except Exception as e:  # noqa: BLE001
        print(f"  Printables indisponível: {e}")
        return []
    finally:
        time.sleep(1)
    return ((resp.get("data") or {}).get(campo) or {}).get("items") or []


def miniatura(caminho):
    """Foto em 320x240 (uns 10 KB) em vez da original, que pode ter vários MB."""
    if not caminho or "." not in caminho.rsplit("/", 1)[-1]:
        return f"https://media.printables.com/{caminho}"
    pasta, arquivo = caminho.rsplit("/", 1)
    nome, ext = arquivo.rsplit(".", 1)
    ext = ext.lower()
    return f"https://media.printables.com/{pasta}/thumbs/inside/320x240/{ext}/{nome}.webp"


def montar_modelo(it, categoria):
    mid = str(it["id"])
    licenca = (it.get("license") or {}).get("abbreviation")
    return {
        "id": mid,
        "nome": it["name"],
        "url": f"https://www.printables.com/model/{mid}-{it['slug']}",
        "imagem": miniatura((it.get("image") or {}).get("filePath", "")),
        "categoria": categoria,
        "downloads": it.get("downloadCount") or 0,
        "curtidas": it.get("likesCount") or 0,
        "publicado": (it.get("datePublished") or "")[:10],
        "licenca": licenca or "?",
        "pode_vender": classificar_licenca(licenca),
        "tags": [t["name"].lower() for t in (it.get("tags") or [])][:12],
        "autor": (it.get("user") or {}).get("publicUsername") or "",
        "pontos": 0,
    }


def coletar_printables(cfg):
    """Modelos mais baixados/curtidos da semana, nas categorias do config."""
    modelos = {}
    lim = cfg["printables_por_categoria"]
    for cat_id, cat_nome in cfg["printables_categorias"].items():
        for ordem in ("-download_count_7_days", "-likes_count_7_days"):
            print(f"Printables: {cat_nome} {ordem}")
            itens = consultar_printables(PRINTABLES_QUERY, {"cat": cat_id, "ord": ordem, "lim": lim}, "morePrints")
            for pos, it in enumerate(itens):
                m = modelos.setdefault(str(it["id"]), montar_modelo(it, cat_nome))
                # quanto mais alto no ranking da semana, mais pontos
                m["pontos"] += lim - pos
    return sorted(modelos.values(), key=lambda m: m["pontos"], reverse=True)


def texto_modelo(m):
    return (m["nome"] + " " + " ".join(m["tags"])).lower()


def coletar_linhas(cfg):
    """Para cada linha de produto: os modelos mais populares dela no Printables."""
    linhas = []
    for linha in cfg["linhas"]:
        modelos = []
        if linha["printables"]:
            print(f"Printables: linha {linha['nome']}")
            itens = consultar_printables(PRINTABLES_BUSCA, {"q": linha["printables"], "lim": cfg["printables_por_linha"]},
                                         "searchPrints2")
            modelos = [montar_modelo(it, linha["nome"]) for it in itens]
        linhas.append({"nome": linha["nome"], "palavras": linha["palavras"], "modelos": modelos})
    return linhas


def resumir_linhas(linhas, semana, sugestoes):
    """Junta tudo por linha: crescimento dos modelos, presença no ranking da semana e buscas novas."""
    for ln in linhas:
        padrao = re.compile(r"\b(" + "|".join(map(re.escape, ln["palavras"])) + r")\b") if ln["palavras"] else None
        em_alta = [m for m in semana if padrao and padrao.search(texto_modelo(m))]
        ln["em_alta_semana"] = len(em_alta)
        ln["destaques_semana"] = [m["id"] for m in em_alta[:6]]
        ln["ganho_downloads"] = sum(m["ganho_downloads"] or 0 for m in ln["modelos"])
        ln["buscas_novas"] = sum(1 for s in sugestoes if s["termo"] == ln["nome"] and s["nova"])
        ln["modelos"].sort(key=lambda m: (m["ganho_downloads"] or 0, m["downloads"]), reverse=True)
        ln["modelos"] = ln["modelos"][:8]
        del ln["palavras"]
    # nota simples para ordenar: presença no ranking da semana pesa mais
    for ln in linhas:
        ln["nota"] = ln["em_alta_semana"] * 10 + ln["buscas_novas"] * 5 + ln["ganho_downloads"] / 100
    linhas.sort(key=lambda ln: ln["nota"], reverse=True)
    return linhas


def marcar_crescimento(modelos, fotos):
    """Compara downloads de hoje com a foto mais antiga dos últimos 7 dias."""
    base = {}
    for foto in fotos[:7]:  # do mais recente ao de 7 dias atrás; o mais antigo sobrescreve
        base.update(foto.get("printables", {}))
    for m in modelos:
        antes = base.get(m["id"])
        if antes is None:
            m["novo_no_ranking"] = bool(fotos)
            m["ganho_downloads"] = None
        else:
            m["novo_no_ranking"] = False
            m["ganho_downloads"] = m["downloads"] - antes.get("downloads", m["downloads"])


# tags que aparecem em tudo e não dizem nada sobre o tema
TAGS_GENERICAS = {
    "decoration", "decor", "homedecor", "home", "3dprint", "3dprinting", "3d", "print", "printable",
    "design", "art", "model", "gift", "cute", "fun", "easy", "noprint", "nosupports", "no-supports",
    "printinplace", "bambulab", "prusa", "multicolor", "multicolour", "home decor", "home-decor",
}


def tags_em_alta(modelos, fotos):
    cont = Counter()
    for m in modelos:
        for t in m["tags"]:
            if t not in TAGS_GENERICAS:
                cont[t] += m["pontos"]
    ontem = {t: i for i, t in enumerate((fotos[0].get("tags_top") if fotos else []) or [])}
    saida = []
    for pos, (tag, pts) in enumerate(cont.most_common(40)):
        pos_antes = ontem.get(tag)
        saida.append({
            "tag": tag,
            "pontos": pts,
            "variacao": None if pos_antes is None else pos_antes - pos,  # positivo = subiu
            "nova": bool(fotos) and pos_antes is None,
        })
    return saida


# ---------- Google autocompletar ----------

def coletar_sugestoes(cfg):
    sugestoes = {}
    pares = [(linha["nome"], termo) for linha in cfg["linhas"] for termo in linha["google"]]
    for linha_nome, termo in pares:
        for suf in cfg["sufixos_busca"]:
            consulta = termo + suf
            url = ("https://suggestqueries.google.com/complete/search?client=firefox&hl=pt-BR&gl=br"
                   "&ie=utf-8&oe=utf-8&q=" + urllib.parse.quote(consulta))
            try:
                resp = baixar(url)
            except Exception as e:  # noqa: BLE001
                print(f"  Google indisponível para '{consulta}': {e}")
                continue
            for s in resp[1] if len(resp) > 1 else []:
                s = s.strip().lower()
                if s and s != consulta.strip().lower():
                    sugestoes.setdefault(s, linha_nome)
            time.sleep(0.7)
    print(f"Google: {len(sugestoes)} sugestões")
    return sugestoes


def marcar_sugestoes_novas(sugestoes, fotos):
    ja_vistas = set()
    for foto in fotos[:30]:
        ja_vistas.update(foto.get("sugestoes", []))
    return [
        {"busca": s, "termo": t, "nova": bool(fotos) and s not in ja_vistas}
        for s, t in sorted(sugestoes.items(), key=lambda kv: (kv[1], kv[0]))
    ]


# ---------- Mercado Livre (opcional) ----------

def coletar_mercado_livre(cfg):
    cid, segredo = os.environ.get("ML_CLIENT_ID"), os.environ.get("ML_CLIENT_SECRET")
    if not (cid and segredo):
        return {"ativo": False, "motivo": "sem chave (ML_CLIENT_ID / ML_CLIENT_SECRET)"}
    try:
        tok = baixar(
            "https://api.mercadolibre.com/oauth/token",
            urllib.parse.urlencode({"grant_type": "client_credentials",
                                    "client_id": cid, "client_secret": segredo}),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )["access_token"]
        auth = {"Authorization": f"Bearer {tok}"}
        tendencias = []
        for cat in cfg.get("ml_categorias", ["MLB1574"]):
            for t in baixar(f"https://api.mercadolibre.com/trends/MLB/{cat}", cabecalhos=auth):
                tendencias.append({"busca": t.get("keyword"), "url": t.get("url"), "categoria": cat})
        print(f"Mercado Livre: {len(tendencias)} buscas em alta")
        return {"ativo": True, "tendencias": tendencias}
    except Exception as e:  # noqa: BLE001
        print(f"Mercado Livre falhou: {e}")
        return {"ativo": False, "motivo": f"erro: {e}"}


# ---------- datas comerciais ----------

def proximas_datas(cfg, hoje):
    saida = []
    for d in cfg["datas_comerciais"]:
        mes, dia = map(int, d["data"].split("-"))
        alvo = date(hoje.year, mes, dia)
        if alvo < hoje:
            alvo = date(hoje.year + 1, mes, dia)
        faltam = (alvo - hoje).days
        if faltam <= cfg["dias_alerta_data"]:
            saida.append({"nome": d["nome"], "data": alvo.isoformat(), "faltam_dias": faltam})
    return sorted(saida, key=lambda x: x["faltam_dias"])


# ---------- Telegram (opcional) ----------

def avisar_telegram(rel):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    linhas = [f"Radar Decor 3D, {rel['data']}", ""]
    linhas.append("Suas linhas mais quentes: " + ", ".join(ln["nome"] for ln in rel["linhas"][:3]))
    linhas.append("")
    vendaveis = [m for m in rel["printables"] if m["pode_vender"] == "sim"][:5]
    if vendaveis:
        linhas.append("Em alta e com licença que permite vender:")
        linhas += [f"- {m['nome']} ({m['downloads']} downloads)\n  {m['url']}" for m in vendaveis]
    subindo = [t["tag"] for t in rel["tags"] if (t["variacao"] or 0) >= 3 or t["nova"]][:8]
    if subindo:
        linhas += ["", "Temas subindo: " + ", ".join(subindo)]
    novas = [s["busca"] for s in rel["sugestoes"] if s["nova"]][:8]
    if novas:
        linhas += ["", "Buscas novas no Google: " + "; ".join(novas)]
    for d in rel["datas"][:2]:
        linhas += ["", f"Faltam {d['faltam_dias']} dias para {d['nome']}"]
    if os.environ.get("PAINEL_URL"):
        linhas += ["", "Painel: " + os.environ["PAINEL_URL"]]
    try:
        baixar(f"https://api.telegram.org/bot{token}/sendMessage",
               urllib.parse.urlencode({"chat_id": chat, "text": "\n".join(linhas),
                                       "disable_web_page_preview": "true"}),
               {"Content-Type": "application/x-www-form-urlencoded"})
        print("Telegram: enviado")
    except Exception as e:  # noqa: BLE001
        print(f"Telegram falhou: {e}")


# ---------- principal ----------

def main():
    cfg = ler_json(RAIZ / "config.json")
    hoje = datetime.now(FUSO_BR).date()
    fotos = historico_anterior(hoje)

    modelos = coletar_printables(cfg)
    linhas = coletar_linhas(cfg)
    modelos_linhas = [m for ln in linhas for m in ln["modelos"]]
    marcar_crescimento(modelos + modelos_linhas, fotos)
    tags = tags_em_alta(modelos, fotos)
    sugestoes = coletar_sugestoes(cfg)
    lista_sugestoes = marcar_sugestoes_novas(sugestoes, fotos)

    rel = {
        "data": hoje.isoformat(),
        "gerado_em": datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M"),
        "dias_de_historico": len(fotos),
        "linhas": resumir_linhas(linhas, modelos, lista_sugestoes),
        "printables": modelos,
        "tags": tags,
        "sugestoes": lista_sugestoes,
        "mercado_livre": coletar_mercado_livre(cfg),
        "datas": proximas_datas(cfg, hoje),
    }
    gravar_json(DADOS / "hoje.json", rel)
    gravar_json(HISTORICO / f"{hoje.isoformat()}.json", {
        "data": hoje.isoformat(),
        "printables": {m["id"]: {"downloads": m["downloads"], "curtidas": m["curtidas"]}
                       for m in modelos + modelos_linhas},
        "tags_top": [t["tag"] for t in tags],
        "sugestoes": sorted(sugestoes),
    })

    limite = (hoje - timedelta(days=DIAS_HISTORICO)).isoformat()
    for arq in HISTORICO.glob("*.json"):
        if arq.stem < limite:
            arq.unlink()

    print(f"Pronto: {len(modelos)} modelos, {len(tags)} temas, {len(sugestoes)} buscas")
    avisar_telegram(rel)


if __name__ == "__main__":
    main()
