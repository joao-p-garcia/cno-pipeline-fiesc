# Decisões técnicas

Complemento do [README](README.md). O README explica como rodar; aqui ficam os
motivos de cada parte do sistema, com as medições que sustentam cada escolha.

---

## Decisões técnicas

**O snapshot é identificado pela data de publicação da fonte**, lida do
`Last-Modified`, e não pela data de execução. Reprocessar amanhã não cria um
snapshot novo para os mesmos dados.

**A idempotência é controlada por ETag local.** O share da Receita não respeita
`If-None-Match` e reenvia os 315 MB inteiros. Um `HEAD` traz o ETag, que é
comparado com o do último snapshot para decidir se precisa baixar.

**O suporte a `Range` é testado com uma requisição de 1 byte.** O `HEAD` não
devolve `Accept-Ranges`, embora o servidor responda `206`. Confiar no cabeçalho
faria o pipeline baixar tudo de novo a cada falha de rede.

**O download vai para um `.part`** e só recebe o nome final depois da conferência
de tamanho, para uma interrupção nunca deixar um arquivo truncado parecendo
completo.

**A descompactação valida o pacote antes de escrever.** Rejeita membros com
caminho (`zip-slip`) e falha se algum dos cinco arquivos esperados faltar.

**Os totais oficiais da Receita entram no manifesto.** O `cno_totais.csv` traz as
contagens de cada tabela (3.604.156 obras, 4.553.076 áreas, 3.942.713 CNAEs,
431.211 vínculos), e a validação reconcilia contra eles.

### Tratamento

**Só o arquivo que precisa é transcodificado para UTF-8.** cp1252 e ISO-8859-1
só divergem na faixa `0x80-0x9F`. Um arquivo sem bytes nessa faixa pode ser lido
direto como `latin-1`. Na base atual só o `cno.csv` tem esses bytes, e a decisão
é feita por varredura do conteúdo, não por lista de nomes. O arquivo convertido é
reaproveitado entre execuções e invalidado pelo sha256 da origem.

Corrigir os caracteres em SQL depois de carregar como `latin-1` exigiria tratar
coluna por coluna, e esquecer uma seria corrupção invisível.

**DuckDB em vez de pandas ou polars.** Leitura completa do `cno.csv` (884 MB,
3,6 M linhas), cada uma em processo isolado:

| | tempo | pico de RAM |
|---|---|---|
| DuckDB no UTF-8 | **0,8s** | **457 MB** |
| Polars `windows-1252` | 4,3s | 2.641 MB |
| pandas `cp1252` | 19,6s | 4.031 MB |

O Polars lê cp1252, mas só na API eager (o `scan_csv` aceita apenas `utf8`), então
a tabela inteira precisa caber na memória. O DuckDB também foi o único que
recusou um arquivo declarado `latin-1` com bytes C1, e foi isso que revelou o
encoding real da base.

**Tudo é lido como texto e convertido com `TRY_CAST`**, para um valor ruim virar
`NULL` em vez de derrubar a carga inteira.

**Identificadores são texto.** `cno`, `cep`, `ni_responsavel` e os códigos de
município e qualificação têm zeros à esquerda (`010010092278`).

**Flags booleanas nunca são nulas.** `NULL LIKE '%+%'` devolve `NULL`, e
`WHERE NOT tem_plus_code` descartaria os 40,78% de registros sem código. Todas as
flags passam por `coalesce(..., false)`.

**Nada é excluído por suspeita.** As 323 obras com área implausível recebem
`area_suspeita = true` e continuam na tabela.

**Os 66,39% de nulos em `ni_responsavel` viram `responsavel_tipo`.** A Receita
deixa o campo em branco quando o responsável é pessoa física.

**O particionamento é por `snapshot_date` e `uf`.** Uma consulta de Santa
Catarina lê 239 mil linhas em vez de 3,6 milhões.

### Validação

**Reconciliação contra a fonte.** A validação compara o carregado com as
contagens do `cno_totais.csv`. É a única checagem que olha para fora do pipeline
e pegaria uma extração que perdeu metade do arquivo. A comparação usa a contagem
antes da deduplicação, porque é isso que a Receita conta.

**Cada regra é um SELECT do que está errado.** Conjunto vazio significa regra
cumprida. Acrescentar uma regra é escrever uma consulta.

**Erro reprova, aviso não.** `ERRO` é violação de contrato (chave duplicada,
órfão, valor fora de domínio) e derruba a execução. `AVISO` é sujeira conhecida
da fonte, medida e acompanhada.

**Regra que não roda falha.** Se o SQL de uma regra quebrar, a validação levanta
erro em vez de contar zero violações.

Resultado no snapshot atual: reconciliação exata nas quatro tabelas, 17 das 19
regras cumpridas e 2 avisos (323 áreas implausíveis e 2 obras sem UF).

### Orquestração

**A DAG só encadeia os comandos** que também se roda na mão, sem regra de
negócio. A lógica fica testável fora do Airflow, e reproduzir uma falha é copiar
um comando do log.

**Duas execuções sobre o mesmo snapshot não se atropelam.** `cno transform` e
`cno curate` apagam a partição e depois a reescrevem com `COPY ... PARTITION_BY`.
Duas execuções nesse intervalo gerariam uma partição pela metade, sem exceção
nenhuma. O `max_active_runs=1` da DAG não cobre dois terminais abertos nem o
container, então a trava fica dentro da etapa (`cno_pipeline/bloqueio.py`).

É um `flock` do sistema operacional, por snapshot. Diferente de um
arquivo-sentinela, ele é liberado pelo kernel quando o processo morre, inclusive
num `SIGKILL`, então não existe trava órfã. `transform` e `curate` usam a mesma
trava, porque a curadoria lê a staging que o tratamento reescreve. A etapa recusa
na hora, dizendo quem detém a trava, em vez de esperar.

**O pipeline é chamado como subprocesso, não importado.** Assim ele pode ser
atualizado sem reinstalar o Airflow, e a falha chega como código de saída. O
contrato entre os dois é a linha de comando e um JSON.

**Não há sensor de novidade.** O `cno extract` já compara o ETag e termina em
menos de um segundo quando não há publicação nova. Um gate na DAG duplicaria essa
regra.

**Retry só na extração.** `extract` tem 3 tentativas com backoff exponencial,
porque depende de rede e o download é resumível. As outras etapas são
determinísticas e falhariam de novo.

**O `snapshot_id` passa de uma etapa para a outra**, para uma publicação nova no
meio da execução não misturar dois snapshots.

### Curadoria

**A staging é fiel à origem, e a curada toma as decisões.** A staging tem quatro
tabelas e uma linha por registro publicado, boa para auditar e ruim para
responder "quantos m² Joinville construiu em 2023".

**`area_m2` só existe quando a unidade é m² e a área não é suspeita.** São dois
problemas independentes. A base mistura unidades (3.404.652 obras em m², 21.328
em km, 14.539 em m³, 3.580 em kW e 156.712 em "Outra"), e 323 obras declaram área
impossível, a maior com 555.555.555.555 m².

| Critério | km² |
|---|---:|
| `SUM(area_total)` cru | **887.114** |
| só tirando as áreas implausíveis | 49.286 |
| só pegando o que está em m² | 840.668 |
| m² **e** sem implausíveis (`area_m2`) | **2.839** |

A soma crua é 312 vezes maior que a correta, e cada filtro sozinho ainda erra por
uma ordem de grandeza. A área declarada continua na tabela.

**A geocodificação não usa serviço externo.** Só 36,4% dos registros têm Plus
Code completo. Outros 6,2% vêm na forma curta (`RF8J+VH`), sem o bloco de 1°, e
são recuperados usando como âncora a mediana dos pontos já decodificados do mesmo
município. Isso cobre 226.854 dos 227.074 códigos curtos.

**Um Plus Code pode ser válido e estar errado.** 48.436 pontos (3,7%) caem a mais
de 150 km do município declarado, 39 mil deles a mais de 500 km, alguns no Japão.
A tabela grava `geo_distancia_municipio_km` e `geo_plausivel`, os marts contam só
o ponto plausível, e a coordenada crua fica para auditoria. A cobertura publicada
é **41,2%**, não os 42,5% brutos nem os 59% de registros com `+`.

**O recorte setorial é por divisão da CNAE.** 100% da base é seção F. As divisões
são 41 Construção de edifícios (1,9 M), 43 Serviços especializados (1,4 M) e 42
Obras de infraestrutura (283 mil), e infraestrutura é 7% das obras e 29% dos
metros quadrados.

**Os marts existem por causa do dashboard.** As três tabelas agregadas têm de 12
mil a 133 mil linhas e usam as mesmas definições de `obras_analitico`. Um teste
confere que os três somam o mesmo que ela.

**A curadoria roda depois da validação**, para nenhum número ser publicado em
cima de dado reprovado.

**Dado externo não entra aqui.** População, PIB e malha municipal ficam na camada
de análise. O pipeline reconcilia contra a fonte, e um dado que a fonte não
publica não tem como ser reconciliado.

**`serie_comparavel` corta em 2019.** Obras por ano de início vão de 87.574
(2016) para 307.530 (2019) e estabilizam perto de 300 mil. O CNO foi criado pela
IN RFB 1.845, de 22/11/2018, e passou a valer em 21/01/2019. A `data_registro`
mais antiga é 19/11/2018, e 2018 tem 385 registros contra 366 mil em 2019.

Não houve migração em bloco: as obras iniciadas antes de 2019 entraram em todos
os anos, mais em 2021 (215.759) do que em 2019 (191.059). 1,6 M de obras (45% da
base) foram cadastradas mais de um ano depois de começar. Por isso o passado é
subcontado e muda a cada snapshot. As consultas `entrada_no_cadastro`,
`registro_de_obras_antigas` e `atraso_de_registro` mostram isso no dashboard e no
caderno.

### Fronteira de dados externos

**O pipeline processa uma fonte só.** Toda a camada curada é derivável do snapshot
do CNO e reconciliável contra os totais da Receita. Município, população e malha
do IBGE ficam na camada de análise, por três motivos:

- **Falha.** Uma indisponibilidade do IBGE derrubaria o pipeline do CNO, que não
  depende dele.
- **Cadência.** A DAG roda todo dia e o IBGE publica uma vez por ano.
- **Custo.** Trocar a safra da população é trocar um arquivo, não reprocessar
  3,6 M de linhas.

O resultado é uma tabela de referência versionada, regerada por script quando
vence. A DAG `referencias_ibge` avisa quando esse momento chega.

**A junção é por nome normalizado, não por código.** A Receita usa código TOM de
4 dígitos e o IBGE usa código de 7. Normalizar (maiúscula, sem acento, sem hífen
e apóstrofo) casa **5.555 de 5.572 (99,7%)**. Os 17 restantes (`PARATI`/`Paraty`,
`SANTANA DO LIVRAMENTO`/`Sant'Ana do Livramento`, `BOA SAÚDE`/`Januário Cicco`...)
estão numa tabela de correção com o motivo de cada linha.

Com as correções, casam **5.570 de 5.570**. Em SC, o ranking por mil habitantes
não tem nenhum dos municípios do topo absoluto: aparecem Itapoá (58,0), Maravilha
(49,4) e Balneário Piçarras (48,3).

### Containerização

**Uma imagem só, com dois ambientes Python.** O Airflow vem da imagem oficial e o
pipeline fica num venv separado em `/opt/cno/.venv`, chamado pela DAG via
`CNO_BIN`. Assim as versões de `requests` e `urllib3` do pipeline não passam pelo
resolvedor de dependências do Airflow.

**A DAG vai embutida na imagem, não montada do host.** Evita o problema de UID do
compose oficial e permite `docker compose up` a partir de um clone novo. Mexer na
DAG pede `make build`.

**O volume de dados é criado na imagem, com dono `airflow`.** Um volume nomeado
herda o dono do diretório da imagem, o que dispensa `AIRFLOW_UID` e `chown -R`.

**LocalExecutor, não Celery.** A DAG tem quatro tasks em sequência, e Redis,
worker e Flower não trariam paralelismo nenhum. O triggerer também ficou de fora,
porque nenhuma task é deferrable.

**No container, o pipeline não guarda os intermediários.** `CNO_MANTER_ZIP=0` e
`CNO_MANTER_INTERMEDIARIOS=0` economizam ~1,7 GB por snapshot. A idempotência não
depende deles, porque a extração confere os CSVs contra o manifesto.

### Análise e visualização

**Uma camada de consultas, dois consumidores.** `analise/dados.py` tem uma função
por pergunta e é o único lugar com SQL fora do pipeline. O notebook e o dashboard
chamam as mesmas funções.

**O app lê marts.** As exceções são as consultas sobre a distribuição de uma
coluna (unidade, quantis de área, distância dos pontos), que varrem a tabela
analítica.

**Mediana de medianas não é mediana.** Onde a mediana importa, a consulta varre a
tabela analítica em vez do mart.

**Matplotlib no caderno, Altair no app, uma paleta só.** O caderno precisa de
imagem salva no `.ipynb` e o app precisa de *hover*. Cores, grade e tipografia
saem de `analise/estilo.py` nos dois.

**A identidade visual é a do Observatório FIESC, com tema escuro.** Cada cor tem
o contraste WCAG e a separação sob daltonismo anotados no módulo, e há teste que
quebra se uma troca derrubar essas contas. Um outro teste confere que
`app/.streamlit/config.toml` e `analise/estilo.py` usam as mesmas cores.

**Mapa sem GIS.** A junção com o CNO é por código de município, então o GeoJSON é
lido com `json`, sem geopandas. Dois detalhes estão em `analise/malha.py`: o Vega
não enquadra a projeção sozinho quando a geometria divide o gráfico com pontos, e
o sentido de giro dos polígonos segue o D3, que é o contrário do RFC 7946.

**O dashboard é testado sem navegador.** O `AppTest` do Streamlit executa as dez
seções sobre a camada sintética. Foi assim que apareceram uma divisão por zero e
um `iloc[0]` numa seleção vazia.

O `AppTest` só confirma que a página subiu, e vários gráficos aqui somem sem erro
(`alt.Step` com camadas, barra em escala log, polígono no sentido errado). Por
isso outro grupo de testes compila o spec com o mesmo Vega-Lite do navegador e
mede o PNG. `tests/test_contratos_analise.py` confere ainda que o app e o caderno
não têm SQL, que cada chamada a `analise/dados.py` bate com a assinatura (o que
testa o caderno sem executá-lo) e que as constantes da análise são o mesmo objeto
das do pipeline.

**Números em pt-BR nos gráficos.** O Streamlit descarta o `formatLocale` em
`usermeta.embedOptions`, então a troca de separadores é uma expressão Vega dentro
do spec. O `replace` precisa do `/g`, a legenda do mapa declara o próprio
`labelExpr` (que não existe em `LegendConfig`), e o eixo de ano não usa separador.

---

## Sobre os dados

Aqui fiz uma análise inicial dos dados antes de montar a pipeline. Isso serve para evitar erros em produção.
Características apuradas por perfilamento completo da base, que orientam o
tratamento:

- Os CSVs são **cp1252**, não UTF-8 nem ISO-8859-1. O `cno.csv` tem 4.881 bytes
  na faixa `0x80-0x9F` (travessão, aspas curvas, bullet), e ler como `latin-1`
  troca esses caracteres por controles sem dar erro.
- `CNO` é chave primária limpa na tabela principal (zero duplicatas em 3,6 M). As
  tabelas filhas têm duplicatas exatas: 21.449 em áreas e 10.873 em vínculos.
- Integridade referencial perfeita: nenhum órfão nas três tabelas filhas.
- **`NI do responsável` e `Nome empresarial` nulos em 66,39% não são dados
  faltantes.** Ficam em branco quando o responsável é pessoa física.
- `Código de localização` é **Plus Code** em 2,11 M registros (59%), o que permite
  geocodificar sem serviço externo.
- Sujeira conhecida: `1970-01-01` e `1900-01-01` como datas desconhecidas, áreas
  absurdas (máximo de 555.555.555.555 m²) e o campo `Estado` com 35 valores
  distintos, incluindo `'CHILE'` e `'estado'`.
