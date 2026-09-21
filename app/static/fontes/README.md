# Fontes da marca

Montserrat e Open Sans, as duas do brandbook do Observatório FIESC (2025), sob
licença SIL Open Font License 1.1 — ver `OFL.txt`, que vale para as duas.

Estão versionadas em vez de vir de CDN por um motivo só: numa apresentação ao
vivo, fonte que depende de rede é fonte que pode não chegar, e o que chega no
lugar dela é a fonte do sistema. O app inteiro cairia para Segoe UI sem nenhum
erro na tela.

| arquivo | quem lê | para quê |
|---|---|---|
| `Montserrat.woff2` | navegador | títulos do dashboard, `[[theme.fontFaces]]` |
| `OpenSans.woff2` | navegador | corpo de texto e rótulo de gráfico |
| `Montserrat-Regular.ttf` | matplotlib | figuras do `analise/exploracao.ipynb` |
| `Montserrat-SemiBold.ttf` | matplotlib | títulos das mesmas figuras |

Open Sans não tem `.ttf` porque o matplotlib só usa `estilo.FONTE`, que é
Montserrat; `estilo.FONTE_MIUDA` existe para o Vega, que roda no navegador.

## Como refazer

Os `woff2` são o subconjunto `latin` que o Google Fonts serve:

```bash
curl -A "Mozilla/5.0" \
  "https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&family=Open+Sans:wght@400;600&display=swap"
# pegue a URL .woff2 de cada bloco @font-face comentado com /* latin */
```

Os `ttf` saem do `woff2`, e a conversão **não é só trocar o contêiner**: o
Montserrat variável tem instância padrão em `wght=100`, que o matplotlib leria
como Thin. É preciso instanciar os pesos e corrigir os nomes.

```python
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

for peso, sufixo in ((400, "Regular"), (600, "SemiBold")):
    fonte = TTFont("Montserrat.woff2")
    fonte.flavor = None                       # woff2 -> ttf
    fonte = instancer.instantiateVariableFont(fonte, {"wght": peso}, inplace=True)
    fonte["OS/2"].usWeightClass = peso
    for registro in fonte["name"].names:      # nameID 1 agrupa família no matplotlib
        if registro.nameID == 1:
            fonte["name"].setName("Montserrat", 1, registro.platformID,
                                  registro.platEncID, registro.langID)
        elif registro.nameID == 2:
            fonte["name"].setName(sufixo, 2, registro.platformID,
                                  registro.platEncID, registro.langID)
    fonte.save(f"Montserrat-{sufixo}.ttf")
```

Precisa de `brotli` instalado para o `fontTools` abrir `woff2`.
