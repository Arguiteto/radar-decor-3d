# Radar Decor 3D

Robô que roda todo dia às 7h e mostra **o que está em alta em decoração para impressão 3D**, num painel que abre no celular.

**[→ Abrir o painel](https://arguiteto.github.io/radar-decor-3d/)**

## O que o painel mostra

| Bloco | De onde vem | Para que serve |
|-------|-------------|----------------|
| **Globo** (aba inicial) | Google Trends, por estado e cidade, últimos 3 meses | Um ponto por estado (ou cidade). Passe o mouse para ver as linhas mais procuradas ali e o modelo em alta; clique para abrir o mapa. Feito com [cobe](https://github.com/shuding/cobe) |
| **Virais** | Printables (todas as categorias), Google Trends e YouTube | O que está estourando agora: modelos do último mês com mais downloads por dia, buscas em ascensão e o que se procura em vídeo |
| **Mapa** | Google Trends + contorno dos estados do IBGE | Onde cada linha é mais procurada e o que se destaca em cada estado |
| **Modelos** | Printables | Uma aba por linha (troféus, medalhas, chaveiros...) além da aba "Em alta da semana" |
| **Suas linhas** | Printables + Google, por linha de produto | Ranking das suas 30 linhas (luminárias, cachepôs, chaveiros, 1/64, DTF...), da mais quente à mais fria |
| **Datas chegando** | Calendário comercial (`config.json`) | Lembra Natal, Dia das Mães etc. com antecedência |
| **Em alta e pode vender** | Printables, últimos 7 dias | Modelos populares cuja licença permite vender a peça impressa |
| **Temas em alta** | Tags dos modelos mais baixados | Estilos e temas subindo (▲ = subiu desde ontem) |
| **O que o Brasil busca no Google** | Autocompletar do Google, em português | Buscas reais de quem quer comprar; "nova" = apareceu este mês |
| **Mercado Livre** (opcional) | API oficial do Mercado Livre | Buscas em alta em Casa e Decoração |
| **Modelos da semana** | Printables | Galeria com filtro por licença, categoria e palavra |

**Licença:** verde = pode vender (CC0, CC BY, CC BY-SA, CC BY-ND). Vermelho = proibido vender (qualquer "NC"). Amarelo = leia a licença antes de vender.

> Downloads mostram o que está na moda entre quem imprime, não vendas reais. As vendas aparecem melhor no Google e no Mercado Livre.

## Como ligar (uma vez só)

1. Crie um repositório no GitHub chamado `radar-decor-3d` e suba estes arquivos.
2. **Settings → Pages**: Source = *Deploy from a branch*, Branch = `main`, pasta `/ (root)`.
3. **Actions → Radar diário → Run workflow** para rodar a primeira vez. Depois ele roda sozinho todo dia.

O que está **crescendo** começa a aparecer a partir do segundo dia, porque o robô compara com o histórico em `dados/historico/`.

## Sobre o mapa

O Google Trends não tem API oficial e bloqueia quem consulta rápido demais. Por isso o robô vai devagar, atualiza primeiro as linhas mais antigas e guarda o último dado bom em `dados/regioes.json`. Nos primeiros dias o mapa vai se completando aos poucos. As cidades são as que o Google mais segura: elas aparecem quando ele libera.

## Opcional: resumo no Telegram

1. No Telegram, fale com **@BotFather**, mande `/newbot` e copie o token.
2. Mande qualquer mensagem para o seu bot e abra `https://api.telegram.org/bot<TOKEN>/getUpdates` para ver o `chat.id`.
3. No GitHub: **Settings → Secrets and variables → Actions → New repository secret**, crie `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID`.

## Opcional: Pinterest Trends (Brasil)

O código já está pronto e fica desligado até existirem as chaves. Quando o app em developers.pinterest.com for aprovado, crie os secrets (Settings → Secrets and variables → Actions):

- `PINTEREST_APP_ID` e `PINTEREST_APP_SECRET`: na página do app.
- `PINTEREST_REFRESH_TOKEN`: gerado no app (permissão `user_accounts:read`). Com ele o robô renova o acesso sozinho.
- Alternativa: só `PINTEREST_TOKEN` (token de acesso direto), que expira e precisa ser trocado à mão.

Rode o robô uma vez: o bloco "No Pinterest (Brasil)" aparece na aba Virais, com as tendências crescendo, sazonais e do mês em decoração, DIY e design. Se o Pinterest mandar um refresh token novo, o painel avisa para atualizar o secret.

## Opcional: Mercado Livre

1. Crie um app grátis em [developers.mercadolivre.com.br](https://developers.mercadolivre.com.br/).
2. Crie os secrets `ML_CLIENT_ID` e `ML_CLIENT_SECRET` como acima.

Se a chave não funcionar, o painel só esconde esse bloco, e o resto continua normal.

## Ajustar o que ele procura

Tudo fica em `config.json`:
- `linhas`: suas linhas de produto. Cada uma tem `printables` (busca em inglês no Printables), `palavras` (para reconhecer a linha nos modelos da semana) e `google` (buscas em português). Para criar uma linha nova, copie uma existente e troque os textos.
- `printables_categorias`: categorias do Printables que entram no radar.
- `datas_comerciais`: datas fixas. Páscoa, Carnaval, Dia das Mães e dos Pais mudam todo ano, então confira essas.

## Rodar no computador

```
python radar.py
```

Não precisa instalar nada além do Python. Depois abra `index.html` por um servidor local (`python -m http.server`) e acesse `http://localhost:8000`.
