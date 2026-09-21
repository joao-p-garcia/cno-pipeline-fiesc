# Decisões técnicas

Este documento é o complemento do [README](README.md): ele registra **por que**
cada parte do sistema é como é, com as medições que sustentam cada escolha.

O README responde *como rodar*; aqui estão as decisões — incluindo as que
mudaram de ideia no meio do caminho, e o número que provocou a mudança. Quase
nenhuma delas é preferência: quase todas nasceram de algo que a base fez e que
não estava no enunciado.

> Se você está avaliando este projeto e tem pouco tempo, o README basta. Este
> arquivo existe para a pergunta *"por que assim, e não do jeito óbvio?"*.

---

## Decisões técnicas

**O snapshot é identificado pela data de publicação da fonte**, lida do
`Last-Modified`, não pela data em que o pipeline rodou. Reprocessar amanhã não
cria um snapshot novo para os mesmos dados.

**A idempotência é controlada por ETag local.** O share da Receita
**não respeita `If-None-Match`** — responde `200` e reenvia os 315 MB inteiros.
Um `HEAD` retorna o ETag, que é comparado com o último snapshot para saber se precisa baixar hoje.

**O suporte a `Range` é detectado por sondagem, não pelo cabeçalho.** O `HEAD`
desta fonte não devolve `Accept-Ranges`, embora o servidor responda `206` a um
`GET` com `Range`. Acreditar no cabeçalho faria o pipeline rebaixar tudo do zero
a cada falha de rede, então uma requisição de 1 byte resolve a dúvida e habilita
download resumível.

**Os dados são baixados para `.part` e só promovidos ao nome final após
conferência de tamanho**, de modo que uma interrupção nunca deixa um arquivo
truncado parecendo completo.

**A descompactação valida o pacote antes de escrever**: rejeita membros com
caminho (`zip-slip`) e falha explicitamente se algum dos cinco arquivos
esperados sumir, em vez de produzir uma camada raw silenciosamente incompleta.

**Os totais oficiais da Receita viram parte do manifesto.** O `cno_totais.csv`
publica as contagens de cada tabela (3.604.156 obras, 4.553.076 áreas,
3.942.713 cnaes, 431.211 vínculos). Registrá-los na extração dá à etapa de
validação um oráculo externo para reconciliar, em vez de o pipeline conferir
apenas contra si mesmo.

### Tratamento

**Só o arquivo que precisa é transcodificado para UTF-8.**

cp1252 e ISO-8859-1 são idênticos em `0x00-0x7F` e `0xA0-0xFF`. Divergem
*somente* em `0x80-0x9F` — onde cp1252 põe tipografia e ISO-8859-1 deixa
controles indefinidos. Um arquivo sem nenhum byte nessa faixa, portanto,
decodifica exatamente igual nos dois, e o DuckDB pode lê-lo direto como
`latin-1`, sem intermediário. Na base atual isso vale para 4 dos 5 arquivos; só
o `cno.csv` tem os tais bytes, e só ele é convertido. A decisão é tomada por
varredura de conteúdo, não por lista de nomes, então uma publicação futura que
introduza tipografia em outra tabela se resolve sozinha.

A conversão em si é trabalho inevitável: bytes cp1252 precisam virar texto
Unicode em algum momento, e todo engine faz isso. A diferença é só *onde*.
pandas e polars convertem em memória a cada leitura; aqui convertemos uma vez em
disco e reaproveitamos, invalidando pelo sha256 da origem.

A alternativa de carregar tudo como `latin-1` e corrigir os caracteres em SQL foi
descartada: exigiria aplicar a correção coluna a coluna, e esquecer uma seria
corrupção invisível.

**Por que DuckDB e não pandas ou polars.** Medido na leitura completa do
`cno.csv` (884 MB, 3,6 M linhas), cada abordagem em processo isolado:

| | tempo | pico de RAM |
|---|---|---|
| DuckDB no UTF-8 | **0,8s** | **457 MB** |
| Polars `windows-1252` | 4,3s | 2.641 MB |
| pandas `cp1252` | 19,6s | 4.031 MB |

Polars lê cp1252 nativamente, o que eliminaria o passo de conversão — mas só na
API eager: `scan_csv` aceita apenas `utf8`, então a execução lazy fica
indisponível e a tabela inteira precisa caber na memória. Como o pipeline vai
rodar em worker de orquestrador com memória limitada, 457 MB contra 2,6 GB
decide a escolha.

Vale registrar que o DuckDB é também o mais rigoroso dos três: ele **recusa** um
arquivo declarado como `latin-1` que contenha bytes da faixa C1. pandas e polars
aceitariam calados e produziriam caracteres de controle. Foi essa recusa que
revelou o encoding real da base.

**Tudo é lido como texto e convertido com `TRY_CAST`.** Deixar o `read_csv`
inferir tipos faria a carga inteira falhar num único valor ruim. Assim, um valor
inconversível vira `NULL` e as 3,6 M de linhas continuam carregando.

**Identificadores são texto, não número.** `cno`, `cep`, `ni_responsavel` e os
códigos de município e qualificação têm zeros à esquerda que um tipo numérico
destruiria (`010010092278` viraria `10010092278`).

**Flags booleanas nunca são nulas.** Em SQL, `NULL LIKE '%+%'` devolve `NULL`, e
uma flag de três valores é armadilha: `WHERE NOT tem_plus_code` descartaria em
silêncio os 40,78% de registros sem código de localização. Todas as flags passam
por `coalesce(..., false)`.

**Nada é excluído por suspeita.** As 323 obras com área implausível em m² recebem
`area_suspeita = true` e permanecem na tabela. Quem analisa decide o que fazer
com elas; o pipeline não decide por ele.

**Os 66,39% de nulos em `ni_responsavel` viram `responsavel_tipo`.** Não são
dados faltantes: a Receita deixa o campo em branco quando o responsável é pessoa
física. Imputar destruiria a informação.

**O particionamento é por `snapshot_date` e `uf`.** Uma consulta restrita a Santa
Catarina lê só 239 mil linhas em vez de 3,6 milhões.

### Validação

**Reconciliação contra a fonte.** O `cno_totais.csv` publica as contagens
oficiais de cada tabela, e a validação as confronta com o que foi carregado.
É a única checagem que olha para fora do pipeline: todas as outras comparam o
dado com regras que nós mesmos escrevemos e, por isso, não detectariam uma
extração que perdeu metade do arquivo.

A comparação usa a contagem **antes** da deduplicação, porque é isso que a
Receita conta — confrontar o número pós-dedup acusaria divergência justamente
onde o pipeline funcionou.

**Cada regra é um SELECT do que está errado.** Conjunto vazio significa regra
cumprida; o executor conta, amostra exemplos e decide o código de saída.
Acrescentar uma regra é escrever uma consulta, sem tocar em mecânica nenhuma.

**Erro reprova, aviso não.** `ERRO` é violação de contrato — chave duplicada,
órfão, valor fora de domínio — e derruba a execução. `AVISO` é sujeira conhecida
da fonte que queremos medir e acompanhar. Marcar tudo como erro tornaria a
validação inútil, já que um cadastro público de 3,6 milhões de registros sempre
tem sujeira; marcar tudo como aviso a tornaria decorativa.

**Regra que não roda falha alto.** Se o SQL de uma regra quebrar, a validação
levanta erro em vez de contabilizar zero violações — o modo de falha mais
perigoso seria uma regra silenciosamente não avaliada passando por aprovada.

Resultado no snapshot atual: reconciliação exata nas quatro tabelas, 17 das 19
regras cumpridas, 2 avisos (323 áreas implausíveis e 2 obras sem UF).

### Orquestração

**A DAG é fina de propósito.** Ela encadeia os mesmos comandos que se roda na
mão e não contém regra de negócio nenhuma. Isso mantém a lógica testável fora do
Airflow — os 65 testes das etapas rodam sem subir scheduler — e faz com que
reproduzir uma falha de produção seja copiar e colar um comando do log.

**Duas execuções sobre o mesmo snapshot não se atropelam, e a garantia não é do
Airflow.** `cno transform` e `cno curate` reescrevem a partição em dois passos —
`shutil.rmtree(particao)` e, logo depois, um `COPY ... PARTITION_BY`. Entre os
dois há uma janela, e duas execuções dentro dela produzem uma partição pela
metade. O modo de falha é o pior possível: **não levanta exceção**, o `COPY`
termina bem, o parquet é legível, e só a contagem denuncia. Não é hipótese — uma
task órfã já deixou duas execuções se sobreporem aqui; não mordeu por sorte de
escalonamento.

O `max_active_runs=1` da DAG resolve para quem passa pelo Airflow. A trava tem
de valer também para dois terminais abertos, para um `airflow tasks run` avulso
e para o container, então mora **dentro da etapa** (`cno_pipeline/bloqueio.py`),
não no orquestrador.

É um `flock` do sistema operacional, por snapshot, e não um arquivo-sentinela.
A diferença é o que acontece quando o processo morre sem limpar: um sentinela
criado com `O_EXCL` vira lixo permanente, e a próxima execução legítima é
recusada até alguém apagar à mão; o bloqueio do kernel é liberado sozinho
quando o descritor fecha, **inclusive num `SIGKILL` ou numa queda do
container**. Não existe trava órfã.

`transform` e `curate` disputam a **mesma** trava, de propósito: além de cada um
poder atropelar a si mesmo, a curadoria lê a staging que o tratamento reescreve.
Snapshots diferentes têm travas diferentes e seguem em paralelo. A etapa recusa
na hora, com mensagem dizendo quem detém a trava, em vez de esperar — uma task
pendurada é mais difícil de diagnosticar do que uma que falha explicando.

**O pipeline é invocado como subprocesso, não importado.** Os dois pacotes até
convivem no mesmo ambiente (`pip check` passa limpo), mas a fronteira de
processo dá o que a de import não dá: o pipeline pode ser atualizado sem
reinstalar o Airflow, e a etapa que falha devolve um código de saída em vez de
uma exceção que a DAG teria de saber interpretar. O contrato entre os dois é a
linha de comando e um JSON.

**Não há sensor de novidade, e é deliberado.** A tentação seria um
`ShortCircuitOperator` checando o ETag antes de baixar — mas o `cno extract` já
faz exatamente isso e responde em menos de um segundo quando não há publicação
nova. Um gate na DAG duplicaria a regra em dois lugares e criaria o risco de
pular etapas a jusante que ainda não rodaram. A idempotência vive nas etapas.

**Retry só onde ele ajuda.** `extract` tem 3 tentativas com backoff exponencial,
porque depende de rede e o download é resumível — a retentativa continua de onde
parou. `transform` e `validate` são determinísticos: se falharam, falharão de
novo, e retentar só multiplicaria o mesmo erro no log.

**O `snapshot_id` viaja entre as etapas.** A extração devolve qual snapshot
processou e as etapas seguintes o recebem, em vez de cada uma resolver "o mais
recente" sozinha — assim uma publicação da Receita no meio da execução não faz a
DAG misturar dois snapshots.

### Curadoria

**A staging é fiel à origem e é isso que a impede de responder perguntas.** Ela
tem quatro tabelas e uma linha por registro publicado — ótimo para auditar,
inútil para perguntar "quantos m² Joinville construiu em 2023". A camada curada
toma as decisões que a fonte não toma, e as toma num lugar só, explicitamente.

**`area_m2` só existe quando a unidade é metro quadrado e a área não é
suspeita.** São **dois** defeitos independentes, e nenhum filtro resolve
sozinho. Primeiro, a base mistura unidades no mesmo campo: 3.404.652 obras em
m², mas 21.328 em km, 14.539 em m³, 3.580 em kW e 156.712 em "Outra" — são
dutos, rodovias, subestações. Segundo, 323 obras declaram área impossível, a
maior com 555.555.555.555 m².

Somar a coluna e ver o que cada filtro tira:

| Critério | km² |
|---|---:|
| `SUM(area_total)` cru | **887.114** |
| só tirando as áreas implausíveis | 49.286 |
| só pegando o que está em m² | 840.668 |
| m² **e** sem implausíveis (`area_m2`) | **2.839** |

**Um `SUM(area_total)` desavisado publicaria um número 312 vezes maior que o
certo.** As duas linhas do meio mostram por que é preciso aplicar os dois
filtros: cada um sozinho ainda deixa uma ordem de grandeza de erro.

A área declarada continua na tabela ao lado da unidade; o que muda é que existe
uma coluna segura de somar.

**A geocodificação não usa serviço externo, e recupera mais do que parecia.** O
`Código de localização` é Plus Code em parte da base, mas só 36,4% dos registros
trazem um código completo. Outros 6,2% vêm na forma curta (`RF8J+VH`), a que
faltam os 4 caracteres do bloco de 1° — e a recuperação desses normalmente exige
um centroide municipal, ou seja, dado externo. Aqui a âncora sai da própria base:
a **mediana dos pontos já decodificados do mesmo município**. Isso cobre 226.854
dos 227.074 códigos curtos, e 5.516 dos 5.572 municípios têm âncora própria.

**Um Plus Code pode ser válido e estar errado, e 3,7% estão.** Medidos 48.436
pontos que decodificam perfeitamente e caem a mais de 150 km do município
declarado — 39 mil deles a mais de 500 km, alguns no Japão. Por isso a tabela
grava `geo_distancia_municipio_km` e `geo_plausivel`, e os marts contam só o
ponto plausível. A coordenada crua fica gravada para auditoria, como
`area_suspeita` faz na staging: marcar, não apagar. **A cobertura honesta é
41,2%**, não os 42,5% brutos nem os 59% que "contém um `+`" sugeririam.

**O recorte setorial é por divisão da CNAE, não por seção.** O CNO é cadastro de
obra: 100% da base cai na seção F, então agrupar por seção daria uma linha só. As
três divisões que ocorrem são 41 Construção de edifícios (1,9 M), 43 Serviços
especializados (1,4 M) e 42 Obras de infraestrutura (283 mil) — e é aí que a
diferença aparece: infraestrutura é 7% das obras e 29% dos metros quadrados.

**Os marts existem por causa do dashboard.** Um Streamlit não pode varrer 3,6 M
de linhas a cada clique num filtro. As três tabelas agregadas têm de 12 mil a 133
mil linhas, respondem instantaneamente e carregam as mesmas definições da tabela
analítica — o app não recalcula regra de negócio, que é o que impede o dashboard
e o notebook de divergirem com o tempo. Há um teste que confere que os três marts
somam exatamente o mesmo que `obras_analitico`.

**A curadoria roda depois da validação.** É ela que alimenta gráfico e relatório,
e publicar número em cima de dado reprovado é pior do que não publicar número
nenhum. Como a validação derruba a execução quando reprova, chegar na curadoria
já significa que a camada tratada reconcilia com a fonte.

**Dado externo não entra aqui.** População, PIB e malha municipal ficam na camada
de análise, fora do pipeline. O pipeline reconcilia contra a fonte, e um dado que
a fonte não publica não tem como ser reconciliado; além disso, misturar safras
(snapshot de 2026, população de 2022) dentro da mesma linha é o tipo de erro que
não dá sintoma. Se um dia precisar entrar, a forma é uma dimensão `municipios`
separada, nunca colunas na tabela de obras.

**`serie_comparavel` corta em 2019, e o motivo não é o que parecia.** Obras por
ano de início saltam de 87.574 (2016) para 307.530 (2019) e depois estabilizam
perto de 300 mil. Triplicar em dois anos e parar não é assinatura de atividade
econômica.

A explicação intuitiva — *o CNO absorveu de uma vez o estoque da matrícula CEI*
— é falsa, e foi a coluna `data_registro` que a derrubou. Se tivesse havido
migração em bloco, as obras iniciadas antes de 2019 teriam entrado no cadastro
em 2019. Entraram espalhadas por todos os anos, e **mais em 2021 (215.759) do
que em 2019 (191.059)**. Registro atrasado não é evento, é rotina: 1,6 M de
obras — 45% da base — foram cadastradas mais de um ano depois de começarem.

O mecanismo real é mais simples e mais forte: **antes de nov/2018 o cadastro não
existia.** O CNO foi criado pela IN RFB 1.845, de 22/11/2018, e passou a valer
em 21/01/2019; a `data_registro` mais antiga da base é 19/11/2018, e 2018
inteiro tem 385 registros contra 366 mil em 2019. Obra anterior a 2019 só
aparece se alguém a cadastrou depois, o que é parcial e continua acontecendo.

Duas consequências, e as duas mandam cortar em 2019: o passado é **subcontado**,
não inflado, e **não é estável entre snapshots** — uma série que comece em 2016
muda de valor a cada atualização sem que nada tenha sido construído. As
consultas `entrada_no_cadastro`, `registro_de_obras_antigas` e
`atraso_de_registro` deixam essa evidência à vista no dashboard e no caderno,
para que a afirmação não dependa de acreditar na leitura de uma norma.

### Fronteira de dados externos

**O pipeline processa uma fonte só, e isso é uma decisão, não uma limitação.**
Toda a camada curada é derivável do snapshot do CNO e reconciliável contra os
totais que a própria Receita publica. No momento em que uma coluna de
`obras_analitico` viesse de outra fonte, com outra data de referência, a frase
"esta camada reconcilia com a fonte" deixaria de ser verdadeira para a tabela.

Município, população e malha do IBGE entram na **camada de análise**, e os
motivos, em ordem de peso:

**Acoplamento de falha.** Como task da DAG, uma indisponibilidade do IBGE
derrubaria o pipeline do CNO — que não usa o IBGE para nada. Seria deixar um
terceiro que não contribui para o produto principal poder quebrá-lo.

**Cadências incompatíveis.** A DAG roda diariamente; o IBGE publica uma vez por
ano. Seriam 365 buscas do mesmo arquivo, ou lógica condicional para evitá-las —
complexidade para benefício zero.

**Assimetria de custo.** Como tabela separada, trocar a safra da população é
trocar um arquivo. Como coluna na tabela de obras, é reprocessar 3,6 M de linhas
para mudar um dado que nem veio da Receita.

**O resultado não é processo rodando por fora — é tabela de referência
versionada.** A mesma categoria dos nomes das seções da CNAE, que são constantes
em `dominios.py` e ninguém espera que sejam buscados da CONCLA toda noite. O
script ao lado existe para regerar quando vencer, e a DAG `referencias_ibge`
avisa quando esse momento chega.

**A junção é por nome normalizado, não por código.** A Receita usa TOM de 4
dígitos, o IBGE usa código de 7, e a de-para entre os dois não tem fonte
canônica estável. Medido na base real: normalizar (maiúscula, sem acento, sem
hífen e apóstrofo) casa **5.555 de 5.572 (99,7%)**. Os 17 restantes são o
conjunto clássico — `PARATI`/`Paraty`, `SANTANA DO LIVRAMENTO`/`Sant'Ana do
Livramento`, `BOA SAÚDE`/`Januário Cicco` — e viram uma tabela de correção
auditável linha a linha, com o motivo de cada uma. Importar a tabela TOM de
5.570 linhas de um terceiro não evitaria esse trabalho: só o esconderia num
arquivo que não dá para revisar. **Não se evita a de-para; escolhe-se o tamanho
dela.**

Com as correções, o casamento é de **5.570 de 5.570**. E o efeito no resultado é
o esperado: em SC, o ranking por obras por mil habitantes não tem nenhum dos
municípios do topo absoluto — aparecem Itapoá (58,0), Maravilha (49,4) e
Balneário Piçarras (48,3), separando litoral de Oeste. Sem denominador, todo
ranking municipal é um ranking populacional disfarçado.

### Containerização

**Uma imagem só, com dois ambientes Python dentro.** O Airflow vem da imagem
oficial e o pipeline é instalado num venv separado, em `/opt/cno/.venv`, que a
DAG invoca pelo caminho absoluto em `CNO_BIN`. Poderiam dividir o mesmo
ambiente — `pip check` passa limpo com os dois juntos —, mas aí toda subida de
versão do `requests` ou do `urllib3` no pipeline passaria pelo resolvedor de
dependências do Airflow, que fixa versões por necessidade. Dois venvs custam
uns poucos MB e removem esse acoplamento; a fronteira entre eles continua sendo
a mesma que já existia em desenvolvimento, a linha de comando.

**A DAG vai embutida na imagem, não montada do host.** Bind mount de `./dags`
dá edição ao vivo, mas traz o problema de UID do compose oficial (arquivos
criados como root no host) e abre a janela em que scheduler e dag-processor leem
versões diferentes do arquivo. Como o container aqui é entrega e não ambiente de
desenvolvimento, embutir sai mais barato: `docker compose up` funciona a partir
de um clone recém-feito, sem nenhum passo de preparação. Mexer na DAG pede um
`make build`.

**O volume de dados é criado na imagem, com dono `airflow`.** Um volume nomeado
herda dono e permissão do diretório que existe na imagem sob o ponto de
montagem. Criar `/opt/cno/data` já com o dono certo no `Dockerfile` é o que
dispensa a variável `AIRFLOW_UID` e o passo de `chown -R` que o compose oficial
precisa executar como root antes de tudo.

**LocalExecutor, não Celery.** O compose oficial monta Redis, worker e Flower
para dar execução distribuída. Esta DAG tem três tasks em linha reta, e o
gargalo é I/O de rede e disco num processo só — uma fila distribuída
acrescentaria dois serviços e nenhum paralelismo aproveitável. Pelo mesmo
critério ficou de fora o triggerer: nenhuma task aqui é deferrable. São cinco
serviços, cada um com motivo.

**No container, o pipeline não guarda os intermediários.** `CNO_MANTER_ZIP=0` e
`CNO_MANTER_INTERMEDIARIOS=0` economizam ~1,7 GB por snapshot. O que eles
aceleram é o reprocessamento do mesmo snapshot, que é raro; a idempotência não
depende deles, porque a extração confere os CSVs contra o manifesto, não o zip.

### Análise e visualização

**Uma camada de consultas, dois consumidores.** `analise/dados.py` tem uma função
por pergunta, e é o único lugar com SQL fora do pipeline. O notebook e o
dashboard chamam as mesmas funções — se escrevessem o próprio SQL, bastaria um
`WHERE` diferente para divergirem num número, e os dois continuariam rodando sem
erro.

**O app lê marts, não a tabela analítica.** Um Streamlit não pode varrer 3,6 M de
linhas a cada clique. As exceções são as consultas de perfilamento (distribuição
de unidade, quantis de área, distância dos pontos), que são perguntas sobre a
distribuição de uma coluna e não cabem num agregado — e a docstring de cada
função diz qual das duas ela toca.

**Mediana de medianas não é mediana.** O mart guarda a mediana de cada grupo;
somar contagens a partir dele é exato, tirar quantil não é. Onde a mediana é o
argumento, a consulta varre a tabela analítica e paga o preço.

**Matplotlib no caderno, Altair no app, uma paleta só.** O caderno precisa de
imagem embutida no `.ipynb` — é o que faz o avaliador ler sem executar, e é o que
o GitHub renderiza. O app precisa de *hover*. As cores, a grade e a tipografia
saem de `analise/estilo.py` nos dois casos, senão o mesmo achado teria duas caras.

**A identidade é a do Observatório FIESC, e o tema é escuro.** As cores saem do
brandbook de 2025 — Nanquim de fundo, Azul piscina na série, Dourado na
anotação, Montserrat no título e Open Sans no miúdo. O que o projeto acrescenta
ao brandbook é a medição: uma paleta de slide pode ser toda azul, um gráfico não,
porque ali a cor é o dado. Cada escolha tem contraste WCAG contra o fundo e
separação sob daltonismo anotados no módulo, e há teste que quebra se alguém
trocar uma cor e derrubar a conta. Barra maior não ganha cor mais forte, e o que
o gráfico defende fica azul enquanto o resto fica cinza.

O tema tem duas metades que precisam concordar: `app/.streamlit/config.toml` pinta a
página, `analise/estilo.py` pinta o gráfico. Um teste compara as duas — divergir
ali produz o pior tipo de defeito visual, um retângulo de tom ligeiramente
diferente que ninguém reporta porque parece intencional.

**Mapa sem GIS.** Um polígono do GeoJSON é uma lista de pares de coordenadas, e a
junção com o CNO é por código de município — não por geometria. Trazer geopandas
custaria GEOS, PROJ e uma cadeia de binários na imagem para comprar o que `json`
já entrega. Duas surpresas ficaram documentadas em `analise/malha.py`: o Vega não
enquadra a projeção sozinho quando a geometria vem numa camada junto com pontos,
e a convenção de sentido de giro do D3 é **o contrário** da do RFC 7946 — com o
sentido "certo", o mapa vira uma mancha chapada, sem erro nenhum no console.

**O dashboard é testado sem navegador — e `AppTest` não basta.** `AppTest`, do
próprio Streamlit, executa o app e devolve os elementos produzidos; as seis
seções são exercitadas sobre a camada sintética. Foi isso que pegou uma divisão
por zero (num recorte sem área em m²) e um `iloc[0]` numa seleção vazia (numa
série com um ano só) antes de qualquer um dos dois chegar à tela.

Mas ele responde *"a página subiu"*, não *"o gráfico apareceu"* — e nesta base
gráfico que some em silêncio é a regra, não a exceção: `alt.Step` em spec com
camadas devolve um gráfico vazio, barra em escala logarítmica não desenha, e a
malha municipal vira uma mancha chapada se o sentido de giro dos anéis seguir o
RFC 7946 em vez da convenção do D3. Nenhum levanta exceção, e `AppTest` passou
verde em todos.

Por isso há um segundo grupo de testes que **compila o spec pelo mesmo
Vega-Lite do navegador e mede o PNG**. Junto com eles, `tests/test_contratos_analise.py`
trava as invariantes que não são contas e que já erodiram uma vez: que o app e o
caderno não contenham SQL, que cada chamada a `analise/dados.py` bata com a
assinatura real (é o que testa o caderno **sem executá-lo**, já que reexecutá-lo
exige os 3 GB), e que as constantes da análise sejam **o mesmo objeto** das do
pipeline — `is`, não `==`, porque dois inteiros iguais passariam num `==` e
continuariam sendo duas fontes de verdade.

**Número em português é parte do contrato, e quase não era.** O tema carimbava
`formatLocale` em `usermeta.embedOptions`, que é como o vega-embed troca o
locale do d3. O Streamlit **filtra** esse objeto — mantém `theme`, `renderer` e
`padding` e descarta o resto —, então o carimbo saía do Python e morria no
frontend: todo eixo do dashboard vinha com vírgula de milhar, sem nada acusando.
A troca passou a ser expressão Vega dentro do spec, que ninguém filtra, com duas
sutilezas que só apareceram renderizando: sem o `/g` o `replace` do Vega troca
apenas a primeira ocorrência (1.000.000 sai como "1.000,000"), e `labelExpr`
existe em `Legend` mas não em `LegendConfig`, então a legenda do mapa declara a
sua. Eixo de ano opta por sair, senão 2019 viraria "2.019".

---

## Sobre os dados

Aqui fiz uma análise inicial dos dados antes de montar a pipeline. Isso serve para evitar erros em produção.
Características apuradas por perfilamento completo da base, que orientam o
tratamento:

- Os CSVs são **cp1252** (Windows-1252), não UTF-8 e **não ISO-8859-1**. O
  `cno.csv` tem 4.881 bytes na faixa `0x80-0x9F`, que em cp1252 são tipografia
  (travessão, aspas curvas, bullet) e em ISO-8859-1 são controles indefinidos.
  Ler como `latin-1` não dá erro — produz caracteres de controle no lugar do
  texto, corrompendo em silêncio.
- `CNO` é chave primária limpa na tabela principal (zero duplicatas em 3,6 M).
  As tabelas filhas têm duplicatas exatas reais: 21.449 em áreas, 10.873 em
  vínculos.
- Integridade referencial perfeita: nenhum órfão nas três tabelas filhas.
- **`NI do responsável` e `Nome empresarial` nulos em 66,39% não são dados
  faltantes.** Por definição da Receita, ficam em branco quando o responsável é
  pessoa física. Serão modelados como flag PF/PJ, nunca imputados.
- `Código de localização` é **Plus Code** em 2,11 M registros (59%), o que
  permite geocodificação sem serviço externo.
- Sujeira conhecida: `1970-01-01` e `1900-01-01` como sentinelas de data
  desconhecida; áreas absurdas (máximo de 555.555.555.555 m²); campo `Estado`
  com 35 valores distintos, incluindo lixo como `'CHILE'` e `'estado'`.
