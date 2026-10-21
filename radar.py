"""Radar de decoração para impressão 3D.

Roda uma vez por dia (GitHub Actions) e grava em dados/:
  - hoje.json             -> o que o painel (index.html) mostra
  - historico/AAAA-MM-DD.json -> foto do dia, usada para achar o que está crescendo

Fontes:
  - Printables: modelos de decoração mais baixados/curtidos nos últimos 7 dias
  - Printables (geral): virais, modelos novos com muitos downloads por dia
  - Google (autocompletar): o que as pessoas estão digitando no Brasil; YouTube também
  - Google Trends: interesse por estado/cidade e buscas em ascensão
  - Pinterest Trends (opcional): buscas em alta no Brasil, se houver os secrets PINTEREST_*
  - Mercado Livre (opcional): buscas em alta, se houver ML_CLIENT_ID/ML_CLIENT_SECRET
  - Telegram (opcional): resumo no celular, se houver TELEGRAM_TOKEN/TELEGRAM_CHAT_ID

Só usa a biblioteca padrão do Python; não precisa de pip install.
"""

import base64
import http.cookiejar
import json
import os
import re
import time
import urllib.error
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
        ln["modelos"] = ln["modelos"][:16]
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


# ---------- Virais: o que está estourando agora ----------

PRINTABLES_GERAL = """
query($ord: String, $lim: Int, $cursor: String) {
  morePrints(ordering: $ord, limit: $lim, cursor: $cursor) {
    cursor
    items {
      id name slug likesCount downloadCount datePublished
      image { filePath }
      license { abbreviation name }
      tags { name }
      user { publicUsername }
      category { name }
    }
  }
}
"""

# termos técnicos que aparecem nas buscas do YouTube e não são produto
YOUTUBE_TECNICO = re.compile(
    r"\b(abs|pla|petg|tpu|resina|filamento|impressora|ender|bambu|anycubic|creality|elegoo|prusa|cura|slicer|"
    r"fatiador|bico|extrusora|mesa|calibra\w*|configura\w*|erro|problema|como|curso|pre[cç]o|barata|qual|"
    r"o que [eé]|acetona|lixar|warping|stl|software|programa|modelagem|blender|fusion|tinkercad|"
    r"iniciante|review|unboxing|vale a pena|comprar|ganhar dinheiro|neg[oó]cio|empresa|faculdade)\b")


def coletar_virais(cfg, fotos, hoje):
    """Modelos novos com muitos downloads por dia, em qualquer categoria (é ali que nascem as modas)."""
    vistos = {}
    for ordem in ("-download_count_7_days", "-likes_count_7_days"):
        cursor = None
        for pagina in range(cfg.get("virais_paginas", 3)):
            print(f"Printables: virais {ordem} página {pagina + 1}")
            try:
                resp = baixar(PRINTABLES_API, json.dumps({"query": PRINTABLES_GERAL,
                              "variables": {"ord": ordem, "lim": 30, "cursor": cursor}}),
                              {"Content-Type": "application/json"})
            except Exception as e:  # noqa: BLE001
                print(f"  Printables indisponível: {e}")
                break
            finally:
                time.sleep(2)
            bloco = (resp.get("data") or {}).get("morePrints") or {}
            for it in bloco.get("items") or []:
                if str(it["id"]) not in vistos:
                    vistos[str(it["id"])] = montar_modelo(it, (it.get("category") or {}).get("name", ""))
            cursor = bloco.get("cursor")
            if not cursor:
                break

    limite = cfg.get("virais_dias", 30)
    virais = []
    for m in vistos.values():
        try:
            dias = (hoje - date.fromisoformat(m["publicado"])).days
        except ValueError:
            continue
        if 0 <= dias <= limite:
            m["dias_no_ar"] = dias
            m["por_dia"] = round(m["downloads"] / max(1, dias))
            virais.append(m)
    virais.sort(key=lambda m: m["por_dia"], reverse=True)
    virais = virais[:48]

    # posição de ontem, para marcar o que está subindo
    ontem = {mid: i for i, mid in enumerate((fotos[0].get("virais") if fotos else []) or [])}
    for i, m in enumerate(virais):
        antes = ontem.get(m["id"])
        m["subiu"] = None if antes is None else antes - i
        m["novo_viral"] = bool(fotos) and antes is None

    temas = Counter()
    for i, m in enumerate(virais):
        for t in m["tags"]:
            if t not in TAGS_GENERICAS:
                temas[t] += len(virais) - i
    print(f"Virais: {len(virais)} modelos dos últimos {limite} dias")
    return {"modelos": virais, "temas": [t for t, _ in temas.most_common(24)]}


def coletar_youtube(cfg, fotos):
    """O que as pessoas procuram em vídeo sobre impressão 3D (autocompletar do YouTube, Brasil)."""
    achadas = {}
    for base in cfg.get("youtube_bases", ["impressão 3d"]):
        for letra in [""] + list("abcdefghijlmnoprstuv"):
            consulta = f"{base} {letra}".strip()
            url = ("https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&hl=pt-BR&gl=br"
                   "&ie=utf-8&oe=utf-8&q=" + urllib.parse.quote(consulta))
            try:
                resp = baixar(url)
            except Exception as e:  # noqa: BLE001
                print(f"  YouTube indisponível para '{consulta}': {e}")
                continue
            for s in resp[1] if len(resp) > 1 else []:
                s = s.strip().lower()
                resto = s.replace(base, "").strip()
                if len(resto) > 2 and not YOUTUBE_TECNICO.search(resto):
                    achadas.setdefault(s, base)
            time.sleep(0.7)
    ja_vistas = set()
    for foto in fotos[:30]:
        ja_vistas.update(foto.get("youtube", []))
    print(f"YouTube: {len(achadas)} buscas")
    return [{"busca": s, "nova": bool(fotos) and s not in ja_vistas}
            for s in sorted(achadas, key=lambda s: (s in ja_vistas, s))]


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


# ---------- Google Trends: interesse por estado e cidade ----------
#
# O Trends não tem API oficial e bloqueia (erro 429) quem pergunta rápido demais.
# Por isso: vai devagar, tenta de novo com espera, para se for bloqueado várias vezes
# seguidas e guarda o último dado bom de cada linha em dados/regioes.json.
# A cada dia atualiza primeiro as linhas mais antigas, então todas vão sendo renovadas.

TRENDS = "https://trends.google.com/trends"
UA_NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


class Bloqueado(Exception):
    pass


def abrir_trends():
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [("User-Agent", UA_NAVEGADOR), ("Accept-Language", "pt-BR,pt;q=0.9")]
    try:
        op.open(f"{TRENDS}/explore?geo=BR&hl=pt-BR", timeout=30)
    except Exception:  # noqa: BLE001 - mesmo com 429 aqui o Google costuma mandar o cookie
        pass
    return op


def trends_json(op, caminho, params):
    url = f"{TRENDS}/api/{caminho}?hl=pt-BR&tz=180&" + urllib.parse.urlencode(params)
    for espera in (0, 25, 70):
        time.sleep(espera)
        try:
            with op.open(url, timeout=30) as r:
                texto = r.read().decode("utf-8")
            return json.loads(texto[texto.index("{"):])
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            print("  Trends pediu para esperar (429)")
    raise Bloqueado()


def interesse_regional(op, termo):
    req = {"comparisonItem": [{"keyword": termo, "geo": "BR", "time": "today 3-m"}], "category": 0, "property": ""}
    widgets = trends_json(op, "explore", {"req": json.dumps(req)})["widgets"]
    geo = next(w for w in widgets if w["id"].startswith("GEO_MAP"))
    saida = {}
    for res in ("REGION", "CITY"):
        time.sleep(6)
        pedido = dict(geo["request"], resolution=res)
        try:
            dados = trends_json(op, "widgetdata/comparedgeo",
                                {"req": json.dumps(pedido, separators=(",", ":")), "token": geo["token"]})
        except Bloqueado:
            if res == "REGION":
                raise
            print("  cidades bloqueadas hoje, fica o dado anterior")
            continue
        itens = [g for g in dados["default"]["geoMapData"] if g.get("hasData", [True])[0] and g["value"][0] > 0]
        if res == "REGION":
            saida["estados"] = {g["geoCode"].replace("BR-", ""): g["value"][0] for g in itens}
        else:
            saida["cidades"] = [
                {"nome": g["geoName"], "valor": g["value"][0],
                 "lat": (g.get("coordinates") or {}).get("lat"), "lng": (g.get("coordinates") or {}).get("lng")}
                for g in itens[:40]
            ]
    return saida


def buscas_subindo(op, termo):
    """As buscas relacionadas que mais cresceram ("em ascensão" no Google Trends)."""
    req = {"comparisonItem": [{"keyword": termo, "geo": "BR", "time": "today 1-m"}], "category": 0, "property": ""}
    widgets = trends_json(op, "explore", {"req": json.dumps(req)})["widgets"]
    rel = next(w for w in widgets if w["id"].startswith("RELATED_QUERIES"))
    time.sleep(6)
    dados = trends_json(op, "widgetdata/relatedsearches",
                        {"req": json.dumps(rel["request"], separators=(",", ":")), "token": rel["token"]})
    listas = dados["default"]["rankedList"]
    subindo = listas[1]["rankedKeyword"] if len(listas) > 1 else []
    return [{"busca": k["query"], "alta": k.get("formattedValue", "")} for k in subindo[:25]]


def coletar_regioes(cfg, hoje):
    cache = ler_json(DADOS / "regioes.json", {"linhas": {}})
    cache.setdefault("subindo", {"atualizado": "", "termos": []})
    linhas = [ln for ln in cfg["linhas"] if ln["google"]]
    linhas.sort(key=lambda ln: cache["linhas"].get(ln["nome"], {}).get("atualizado", ""))
    limite = time.time() + cfg.get("trends_minutos", 8) * 60
    op = abrir_trends()
    feitas = bloqueios = 0

    # primeiro, o que está subindo em impressão 3D e decoração (uma vez por dia basta)
    if cache["subindo"].get("atualizado") != hoje.isoformat() and cfg.get("trends_minutos", 8) > 0:
        termos = []
        for termo in cfg.get("subindo_termos", ["impressão 3d"]):
            print(f"Trends: buscas subindo para '{termo}'")
            try:
                termos += [dict(t, base=termo) for t in buscas_subindo(op, termo)]
            except Bloqueado:
                bloqueios += 1
                print("  bloqueado, fica o dado anterior")
                break
            except Exception as e:  # noqa: BLE001
                print(f"  falhou: {e}")
            time.sleep(8)
        if termos:
            cache["subindo"] = {"atualizado": hoje.isoformat(), "termos": termos}

    for ln in linhas:
        if time.time() > limite or bloqueios >= 2:
            break
        termo = ln["google"][0]
        print(f"Trends: {ln['nome']} ({termo})")
        try:
            novo = interesse_regional(op, termo)
        except Bloqueado:
            bloqueios += 1
            print("  bloqueado, pulando")
            continue
        except Exception as e:  # noqa: BLE001
            print(f"  Trends falhou: {e}")
            continue
        bloqueios = 0
        antigo = cache["linhas"].get(ln["nome"], {})
        cache["linhas"][ln["nome"]] = {
            "termo": termo,
            "atualizado": hoje.isoformat(),
            "estados": novo.get("estados", {}),
            "cidades": novo.get("cidades", antigo.get("cidades", [])),
        }
        feitas += 1
        time.sleep(8)
    # linhas que saíram do config não ficam no mapa
    nomes = {ln["nome"] for ln in linhas}
    cache["linhas"] = {k: v for k, v in cache["linhas"].items() if k in nomes}
    gravar_json(DADOS / "regioes.json", cache)
    print(f"Trends: {feitas} linha(s) atualizada(s), {len(cache['linhas'])} no mapa")
    return cache


# ---------- Pinterest Trends (opcional) ----------
#
# Fica desligado até existirem os secrets no GitHub:
#   PINTEREST_APP_ID + PINTEREST_APP_SECRET + PINTEREST_REFRESH_TOKEN (renova sozinho)
#   ou PINTEREST_TOKEN (token de acesso direto, que expira e precisa ser trocado à mão)
# Documentação: GET /v5/trends/keywords/{region}/top/{trend_type}, permissão user_accounts:read.

PINTEREST_API = "https://api.pinterest.com/v5"


def token_pinterest():
    app_id, segredo = os.environ.get("PINTEREST_APP_ID"), os.environ.get("PINTEREST_APP_SECRET")
    refresh = os.environ.get("PINTEREST_REFRESH_TOKEN")
    if app_id and segredo and refresh:
        basic = base64.b64encode(f"{app_id}:{segredo}".encode()).decode()
        resp = baixar(f"{PINTEREST_API}/oauth/token",
                      urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}),
                      {"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}"})
        aviso = ""
        if resp.get("refresh_token") and resp["refresh_token"] != refresh:
            aviso = "O Pinterest mandou um refresh token novo: atualize o secret PINTEREST_REFRESH_TOKEN."
            print("  " + aviso)
        dias = resp.get("refresh_token_expires_in")
        if dias:
            aviso = (aviso + " " if aviso else "") + f"O refresh token vale por mais {round(dias / 86400)} dia(s)."
        return resp["access_token"], aviso
    if os.environ.get("PINTEREST_TOKEN"):
        return os.environ["PINTEREST_TOKEN"], "Usando token direto: quando expirar, gere outro no app e troque o secret."
    return None, ""


def coletar_pinterest(cfg):
    try:
        token, aviso = token_pinterest()
    except Exception as e:  # noqa: BLE001
        print(f"Pinterest: não consegui o token ({e})")
        return {"ativo": False, "motivo": f"token recusado: {e}"}
    if not token:
        return {"ativo": False, "motivo": "sem chave (PINTEREST_*)"}
    auth = {"Authorization": f"Bearer {token}"}
    regiao = cfg.get("pinterest_regiao", "BR")
    listas = []
    for tipo in cfg.get("pinterest_tipos", ["growing", "seasonal", "monthly"]):
        for interesse in cfg.get("pinterest_interesses", ["home_decor", "diy_and_crafts", "design"]):
            url = (f"{PINTEREST_API}/trends/keywords/{regiao}/top/{tipo}?"
                   + urllib.parse.urlencode({"interests": interesse, "limit": 50}))
            print(f"Pinterest: {tipo} / {interesse}")
            try:
                resp = baixar(url, cabecalhos=auth)
            except Exception as e:  # noqa: BLE001
                print(f"  falhou: {e}")
                continue
            finally:
                time.sleep(1)
            for i, t in enumerate(resp.get("trends") or []):
                listas.append({
                    "busca": t.get("keyword", ""),
                    "tipo": tipo,
                    "interesse": interesse,
                    "posicao": i + 1,
                    "semana": t.get("pct_growth_wow"),
                    "mes": t.get("pct_growth_mom"),
                    "ano": t.get("pct_growth_yoy"),
                })
    if not listas:
        return {"ativo": False, "motivo": "o Pinterest não devolveu tendências (confira o acesso do app)", "aviso": aviso}
    print(f"Pinterest: {len(listas)} tendências")
    return {"ativo": True, "regiao": regiao, "tendencias": listas, "aviso": aviso}


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
    virais = coletar_virais(cfg, fotos, hoje)
    youtube = coletar_youtube(cfg, fotos)

    rel = {
        "data": hoje.isoformat(),
        "gerado_em": datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M"),
        "dias_de_historico": len(fotos),
        "linhas": resumir_linhas(linhas, modelos, lista_sugestoes),
        "printables": modelos,
        "tags": tags,
        "sugestoes": lista_sugestoes,
        "virais": virais,
        "youtube": youtube,
        "regioes": coletar_regioes(cfg, hoje),
        "pinterest": coletar_pinterest(cfg),
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
        "virais": [m["id"] for m in virais["modelos"]],
        "youtube": [y["busca"] for y in youtube],
    })

    limite = (hoje - timedelta(days=DIAS_HISTORICO)).isoformat()
    for arq in HISTORICO.glob("*.json"):
        if arq.stem < limite:
            arq.unlink()

    print(f"Pronto: {len(modelos)} modelos, {len(tags)} temas, {len(sugestoes)} buscas")
    avisar_telegram(rel)


if __name__ == "__main__":
    main()
