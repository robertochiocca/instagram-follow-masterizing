# Instagram Growth Tool — Personal Edition

Aplicação pessoal, em português, para melhorar o próprio perfil do Instagram de forma
**orgânica e manual**: analisar e escolher fotos, organizar o feed, aprender suas
preferências estéticas, gerar sugestões de bio e legendas, acompanhar perfis e
follow-back e planejar metas de seguidores.

> **O que a aplicação NÃO faz:** não publica, não segue, não deixa de seguir, não
> curte, não envia mensagens, não faz scraping, não usa reconhecimento facial e não
> pede sua senha do Instagram. Nenhuma foto ou dado é enviado a serviços externos.
> Pontuações e projeções são **estimativas** — não há promessa de seguidores,
> alcance ou viralização.

---

## Sumário

1. [Funcionalidades](#funcionalidades)
2. [Pré-requisitos](#pré-requisitos)
3. [Instalação no Linux](#instalação-no-linux)
4. [Execução local](#execução-local)
5. [Execução no GitHub Codespaces](#execução-no-github-codespaces)
6. [Abrir no navegador do tablet/celular Android](#abrir-no-navegador-do-tabletcelular-android)
7. [Configuração (variáveis de ambiente)](#configuração-variáveis-de-ambiente)
8. [Backup, exportação e exclusão de dados](#backup-exportação-e-exclusão-de-dados)
9. [Critérios, pesos e fórmulas](#critérios-pesos-e-fórmulas)
10. [Integração com o Instagram](#integração-com-o-instagram)
11. [Privacidade e segurança](#privacidade-e-segurança)
12. [Testes](#testes)
13. [Limitações conhecidas](#limitações-conhecidas)
14. [Atualizar dependências](#atualizar-dependências)
15. [Encerrar o ambiente remoto](#encerrar-o-ambiente-remoto)
16. [Arquitetura](#arquitetura)

---

## Funcionalidades

| Página | O que faz |
|---|---|
| **Dashboard** | Seguidores atuais, meta, ganho líquido, crescimento %, posts, alcance, visualizações, visitas e engajamento (quando informados). Gráfico de evolução, tabelas semanal e mensal, registro manual, importação/exportação CSV e **simulador de metas** com cenários conservador/intermediário/otimista e plano de ritmo necessário (ex.: 69 → 1.000 ou 3.000). |
| **Minhas fotos** | Upload múltiplo (JPG, JPEG, PNG, WEBP), validação, análise de brilho, contraste, nitidez, áreas estouradas, cor, resolução e composição; pontuação técnica 0–100 explicada; observações sobre luz e enquadramento; nota manual, comentários, tags, categorias, favorita e exclusão. |
| **Organizador do feed** | Seleção das fotos, sugestão automática de ordem, prévia da grade 3×N, mover/fixar/retirar fotos (fotos fixadas mantêm a posição quando outras saem), detecção de fotos quase iguais e de repetição de luz/tema, sugestões de alternância, versões salvas, comparação lado a lado e exportação (CSV, PNG da grade e ZIP com fotos numeradas **na ordem de publicação**). |
| **Minhas referências** | Upload de imagens que você admira, paleta de cores, categorias, enquadramento, iluminação (com sugestão automática), contexto, estilo de roupa, nota 1–5, Gosto/Neutro/Não gosto e notas. Aba “O que aprendi” com preferências explicadas e comparação com as suas fotos. |
| **Meu perfil** | Dados do perfil, quatro estilos de bio (curta, minimalista, esportes/lifestyle, viagens/internacional) em PT e EN, comparação com a bio atual por checklist, destaques sugeridos e ordenados, legendas por tema, ideias de posts/Reels, chamadas discretas e diagnóstico explicado. |
| **Perfis de interesse** | Lista manual (usuário ou URL), categoria, motivo, origem, prioridade, status, tags e notas; pesquisa, filtros, ordenação, edição, arquivamento, exclusão e exportação CSV. |
| **Acompanhamento** | Registro manual de quem você seguiu e se houve follow-back; filtros por status e período, revisão, arquivamento, exclusão, taxa de follow-back e exportação. |
| **Planejador de conteúdo** | Calendário (ideia → planejado → publicado), rotina sugerida configurável (padrão: 2 Reels + 1 carrossel por semana + Stories), métricas pós-publicação e comparação de resultados por tipo e tema. |
| **Configurações** | Categorias estéticas editáveis e com importância ajustável, listas, pesos da pontuação e do aprendizado, limite de upload, meta, exportação completa, backup e exclusão de dados. |

---

## Pré-requisitos

- **Python 3.11 ou superior** (testado em 3.11 e 3.13).
- **Git**.
- ~200 MB livres para dependências, mais o espaço das suas fotos.
- Navegador moderno (Chrome no Android funciona bem).

Verifique:

```bash
python3 --version
git --version
```

## Instalação no Linux

```bash
git clone https://github.com/robertochiocca/instagram-follow-masterizing.git
cd instagram-follow-masterizing
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt          # só para usar a aplicação
pip install -r requirements-dev.txt      # opcional: inclui pytest para rodar os testes
```

> No Ubuntu/Debian, se `python3 -m venv` falhar, instale o pacote: `sudo apt install python3-venv`.

## Execução local

```bash
source .venv/bin/activate
streamlit run app.py
```

Abra **http://localhost:8501**. O banco e as imagens são criados automaticamente em
`./data/` (pasta ignorada pelo Git). Por padrão o servidor só aceita conexões do próprio
computador (`address = "localhost"` em `.streamlit/config.toml`).

Para encerrar, pressione `Ctrl+C` no terminal.

## Execução no GitHub Codespaces

O repositório inclui `.devcontainer/devcontainer.json`, então o ambiente já vem pronto.

1. No GitHub, abra o repositório → botão **Code** → aba **Codespaces** → **Create codespace on main**
   (funciona também pelo navegador do tablet).
2. Aguarde a instalação automática das dependências (`postCreateCommand`).
3. No terminal do Codespace:
   ```bash
   streamlit run app.py
   ```
4. Uma notificação oferecerá abrir a porta **8501**. Também é possível usar a aba **Ports**
   (Portas) e clicar no ícone de globo da porta 8501.

A porta é **privada** por padrão: só quem estiver logado na sua conta do GitHub consegue abrir.
Mantenha assim. Se tornar a porta pública, defina `IGT_APP_PASSWORD` antes (veja abaixo).

> **Se o upload de arquivos falhar com erro 403** em algum ambiente com proxy, rode
> `streamlit run app.py --server.enableXsrfProtection false` **apenas com a porta privada**.
> Essa proteção extra contra requisições forjadas é desnecessária quando só você acessa,
> mas não a desative em portas públicas.

## Abrir no navegador do tablet/celular Android

**Opção A — Codespaces (recomendada para tablet):**
1. No Chrome do Android, entre em `github.com/codespaces` e abra seu codespace.
2. Rode `streamlit run app.py` no terminal.
3. Na aba **Ports**, toque no globo da porta 8501: abrirá um endereço como
   `https://<nome>-8501.app.github.dev`.
4. Dica: no menu do Chrome, use **Adicionar à tela inicial** para abrir como um app.
   Para a interface aparecer mais larga, você pode ocultar o menu lateral pelo botão `«`.

**Opção B — servidor Linux na mesma rede Wi-Fi:**
```bash
export IGT_APP_PASSWORD='uma-senha-forte'
streamlit run app.py --server.address 0.0.0.0
```
No tablet, abra `http://<IP-do-computador>:8501` (descubra o IP com `hostname -I`).
Use apenas em redes confiáveis: a conexão local não é criptografada (HTTP).

## Configuração (variáveis de ambiente)

Copie `.env.example` para `.env` (o `.env` nunca vai para o Git) ou exporte no terminal.
Todas são opcionais. No `.env`, coloque entre aspas qualquer valor que contenha `#` (por
exemplo uma senha): sem aspas, ` #` inicia um comentário, como no padrão dotenv.

| Variável | Padrão | Função |
|---|---|---|
| `IGT_DATA_DIR` | `./data` | Pasta do banco SQLite e das imagens privadas. |
| `IGT_MAX_UPLOAD_MB` | `15` | Tamanho máximo por imagem (teto 50; também ajustável em Configurações). |
| `IGT_APP_PASSWORD` | vazio | Exige senha para abrir a interface. Recomendado se a porta for exposta. |
| `IGT_TIMEZONE` | `America/Sao_Paulo` | Fuso usado nas datas padrão (servidores remotos costumam usar UTC). Um nome inválido gera um aviso no log e volta ao padrão. |
| `IGT_LOG_LEVEL` | `INFO` | Nível de log. Logs nunca contêm imagens, senhas ou conteúdo privado. |

## Backup, exportação e exclusão de dados

Tudo fica em `data/` (ou em `IGT_DATA_DIR`):

```
data/
├── growth_tool.sqlite3        # banco (perfil, registros, métricas, configurações)
└── images/
    ├── own/{full,thumbs}/     # suas fotos (cópias sem EXIF/GPS) e miniaturas
    └── reference/{full,thumbs}/
```

**Pela interface (Configurações → Dados e privacidade):**
- **Exportação completa (ZIP):** `dados.json` com todas as tabelas, um CSV por tabela e, se
  desejar, as imagens. Os CSVs usam `;`, vírgula decimal e campos entre aspas (padrão do Excel
  em português); o Google Planilhas detecta o formato automaticamente.
- **Backup do banco (.sqlite3):** cópia consistente feita com a API de backup do SQLite.
- **Apagar todas as minhas fotos**, **apagar todas as referências** ou **apagar TODOS os dados**
  (exige digitar `APAGAR`). Cada página também permite excluir registros individuais, sempre com
  confirmação.

**Pelo terminal (com a aplicação parada):**
```bash
# backup completo
tar czf backup-growth-tool-$(date +%Y%m%d).tar.gz data/
# restaurar
tar xzf backup-growth-tool-AAAAMMDD.tar.gz
```

No Codespaces, baixe o backup antes de apagar o ambiente: clique com o botão direito no
arquivo no explorador do VS Code → **Download**.

## Critérios, pesos e fórmulas

### Pontuação técnica da foto (0–100)

É uma **estimativa técnica para comparar suas fotos entre si**. Não mede beleza nem prevê
curtidas. A imagem é reduzida para no máximo 1024 px antes das medidas.

| Critério | Peso padrão | Como é medido | Nota máxima quando |
|---|---|---|---|
| Exposição | 20 | Luminância média | entre 30% e 70% (zero abaixo de 5% ou acima de 95%) |
| Contraste | 15 | Desvio-padrão da luminância | entre 0,16 e 0,30 |
| Nitidez aproximada | 25 | Variância do Laplaciano nos 25% blocos mais nítidos de uma grade 4×4 (não pune fundo desfocado) | ≥ 800 (zero com ≤ 40, escala logarítmica) |
| Áreas estouradas/sem detalhe | 10 | % de pixels quase brancos (≥ 250) + quase pretos (≤ 5) | ≤ 1% (zero com ≥ 15%) |
| Equilíbrio de cor | 10 | Saturação média (HSV) | entre 18% e 55% (pouca cor perde só até 40%, pois pode ser intencional) |
| Resolução | 10 | Lado menor ÷ 1080 px | lado menor ≥ 1080 px |
| Composição (aproximação) | 10 | Centro de massa das bordas comparado aos pontos dos terços (até 1,0) e ao centro (até 0,85); perto da borda vale 60% | detalhe sobre um ponto dos terços |

`total = Σ (peso_normalizado × nota_do_critério) × 100`. Os pesos podem ser alterados em
**Configurações → Pesos**; ao salvar, todas as fotos são reavaliadas.

### Organizador do feed

Algoritmo guloso e explicável. Para cada posição livre (as fixadas não mudam), escolhe a foto que
maximiza:

```
utilidade = Wq·qualidade + Wp·preferência + Wc·coerência − Wd·semelhança_com_vizinhas
```

- **qualidade:** pontuação técnica (0–1); com nota manual vira 70% técnica + 30% nota; favoritas +0,05.
- **preferência:** afinidade com as referências (0,5 = neutro enquanto houver menos de 5 avaliadas).
- **coerência:** `1 − distância Lab da cor média da foto até a cor média do conjunto ÷ 60`.
- **semelhança:** maior semelhança com as vizinhas (esquerda, direita, acima, abaixo) =
  35% hash perceptual (dHash) + 30% tags/cenário/enquadramento + 15% luz + 20% cor.
- Pesos padrão: qualidade 35, diversidade 25, coerência 20, preferência 20 (ajustáveis na página).
- Fotos com dHash a até 10 bits de distância são marcadas como quase iguais.

### Aprendizado de preferências

- Sinal de cada referência: nota 1–5 → `(nota − 3) ÷ 2`; Gosto/Neutro/Não gosto → `+1/0/−1`
  (média dos dois quando houver ambos).
- Para cada característica: `preferência = soma dos sinais ÷ (nº de avaliações + 2)`.
  O “+2” evita conclusões com poucos exemplos.
- Afinidade de uma foto: média das preferências das suas características, ponderada pelos
  pesos dos grupos e pela importância de cada categoria (Configurações).
- Recomendações só aparecem a partir de **5 referências avaliadas**.

### Crescimento e metas

- Ganho líquido = seguidores no fim − seguidores no início (pode ser negativo).
- Crescimento % = ganho líquido ÷ seguidores no início × 100.
- Engajamento = interações ÷ contas alcançadas × 100.
- Cenários a partir do ritmo base `r` (seguidores líquidos/dia) e da margem `m` (padrão 50%):
  conservador `r − m·|r|`, intermediário `r`, otimista `r + m·|r|`.
- Dias até a meta: `⌈(meta − atual) ÷ r⌉` quando `r > 0`; com variação mensal `g`, o ganho do
  dia `d` é `r·(1 + g)^(d/30)`, somado até atingir a meta (horizonte máximo de 5 anos).
- Ritmo necessário: `(meta − atual) ÷ dias do prazo`.

## Integração com o Instagram

A aplicação funciona **100% sem integração**; todos os dados são inseridos por você. Não há
integração implementada, por decisão de projeto. Situação verificada na documentação oficial
da Meta em outubro de 2026:

- A **Instagram API with Instagram Login** atende apenas **contas profissionais** (Criador de
  conteúdo ou Comercial). A antiga Basic Display API, que atendia contas pessoais, foi
  desativada em dezembro de 2024.
- Permissões (escopos) atuais incluem `instagram_business_basic` e
  `instagram_business_manage_insights`. Acesso avançado exige App Review da Meta.
- A API fornece dados do próprio perfil (como `followers_count`), mídia e insights, mas **não**
  fornece a lista de quem você segue nem de quem segue você; por isso o acompanhamento de
  follow-back é manual.
- Métricas de seguidores dos Insights não estão disponíveis para contas com menos de 100 seguidores.

Se uma integração for adicionada no futuro: usar apenas a API oficial, tokens somente em
variáveis de ambiente, nunca pedir ou armazenar a senha do Instagram e manter o modo manual
como alternativa completa.

Referências: [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login),
[Instagram Account Insights](https://developers.facebook.com/docs/instagram-platform/api-reference/instagram-user/insights).

> Alternativa oficial e manual: em **Central de Contas → Suas informações e permissões →
> Baixar suas informações**, o Instagram permite baixar seus dados, incluindo seguidores e
> seguidos. Um importador desse arquivo está listado nas próximas melhorias.

## Privacidade e segurança

- **Uploads validados** por extensão, tamanho e conteúdo real (Pillow), com rejeição de arquivos
  corrompidos, truncados, com extensão trocada ou com dimensões absurdas (proteção contra
  “bombas de descompressão”). Só os decodificadores JPEG, PNG e WEBP do Pillow são usados: um
  arquivo de outro tipo (por exemplo PostScript disfarçado de `.png`, que acionaria o
  Ghostscript) é recusado sem ser decodificado. Fotos de câmera com imagem extra embutida (MPO)
  são aceitas como JPEG.
- **Cópia sanitizada:** as imagens são recodificadas sem nenhum metadado (EXIF com GPS, XMP,
  comentários JPEG) e salvas com nomes aleatórios (UUID). A orientação é aplicada antes (mesmo
  com EXIF malformado), perfis de cor como Display P3 são convertidos para sRGB e imagens de
  16 bits são reduzidas para 8 bits sem estourar. O nome original serve só para exibição.
- **Arquivos privados separados dos estáticos:** imagens ficam em `data/` e são entregues
  apenas pela sessão do Streamlit; `assets/` contém só o CSS.
- **Gravação atômica** (arquivo temporário + renomear); temporários órfãos são apagados ao iniciar.
  Os uploads são processados em memória.
- **SQL parametrizado** e lista de tabelas/colunas permitidas; vocabulários validados por
  restrições `CHECK` no banco.
- **CSV exportado** com proteção contra injeção de fórmulas (`=`, `+`, `-`, `@`) e com todos os
  campos entre aspas, para que um `;` ou `,` dentro de um texto não crie uma célula nova.
- **Exportações preparadas** (ZIP e backup) são descartadas da memória da sessão após qualquer
  alteração ou exclusão, para nunca entregar fotos ou registros já apagados.
- **URLs** aceitam só `http/https`; nenhum link é acessado pelo servidor.
- **Senha opcional** (`IGT_APP_PASSWORD`), comparada em tempo constante e nunca armazenada.
  As páginas ficam em `views/` (e não em `pages/`) de propósito: com uma pasta `pages/`, o
  Streamlit ativa o modo multipágina antigo e permite abrir uma página pela URL sem passar pela
  tela de senha.
- **Servidor local por padrão:** escuta apenas em `localhost`; para usar na rede, é preciso
  passar `--server.address 0.0.0.0` explicitamente (defina a senha antes).
- **Erros:** o navegador mostra mensagens genéricas (`showErrorDetails = "none"`); os detalhes
  vão apenas para o terminal. Para depurar localmente: `streamlit run app.py --client.showErrorDetails=full`.
- **Telemetria do Streamlit desativada** (`gatherUsageStats = false`).
- **Dependências fixadas** em `requirements.txt` e verificadas com `pip-audit`
  (nenhuma vulnerabilidade conhecida na verificação de outubro de 2026).
- **Ambientes remotos:** no Codespaces (ou qualquer servidor), arquivos e banco ficam na
  infraestrutura do provedor enquanto o ambiente existir. Não há privacidade absoluta:
  exporte o que quiser guardar e apague dados e ambiente quando não precisar mais.

## Testes

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Cobrem: inicialização e migração do banco, CRUD, persistência após reinício, validação de
imagens (formatos, arquivos corrompidos/truncados, acima do limite, extensão trocada, bomba de
descompressão, EXIF), armazenamento sanitizado e exclusão, pontuações técnicas, preferências,
algoritmo do feed, crescimento líquido, projeções, importação/exportação CSV, exportação
completa, exclusão total e execução real de todas as páginas (Streamlit AppTest), incluindo
formulários, confirmações de exclusão e a senha de acesso.

## Limitações conhecidas

- A análise é **heurística** (Pillow + NumPy): não reconhece rostos, pessoas, roupas ou cenários.
  Enquadramento, cenário e estilo de roupa são informados por você; a iluminação tem só um palpite
  automático simples.
- A nitidez pode ser superestimada em fotos com muito ruído (grão) e a composição é uma aproximação.
- Formatos HEIC/HEIF (comuns em iPhone) e GIF não são aceitos; converta para JPG antes.
- Ao registrar métricas de uma data que já existe, campos vazios (inclusive “Seguidores”) mantêm
  o valor salvo — dá para completar só o alcance de um dia passado. Para uma data nova, os
  seguidores são obrigatórios. Para apagar um valor, exclua o registro da data e registre de novo.
- A importação CSV recusa datas futuras e números acima de 10¹²; linhas com erro são listadas
  com o número da linha e não impedem a importação das demais.
- As sugestões de texto usam modelos prontos (sem IA generativa); revise-as e personalize.
  A versão em inglês traduz apenas termos comuns.
- Não há sincronização com o Instagram: métricas e follow-backs dependem de registro manual.
- Reordenar o feed é feito por toques (mover para antes/depois), não por arrastar e soltar.
- Uso pensado para **uma pessoa**; não há contas de usuário múltiplas.
- O SQLite é adequado para uso pessoal; para vários usuários simultâneos, migrar para um banco servidor.

### Próximas melhorias recomendadas

1. Importar o arquivo oficial “Baixar suas informações” do Instagram para cruzar seguidores e
   seguidos e atualizar o acompanhamento de follow-back automaticamente (sem scraping).
2. Suporte a HEIC via `pillow-heif` (dependência opcional).
3. Classificação opcional de cenário com um modelo local leve (por exemplo, CLIP via ONNX),
   avaliando custo de instalação e uso de memória antes.
4. Reordenação por arrastar e soltar com um componente compatível com toque.
5. API FastAPI reaproveitando `services/` e `database/` para um frontend independente.

## Atualizar dependências

```bash
source .venv/bin/activate
pip list --outdated
# edite as versões em requirements.txt / requirements-dev.txt (prefira versões com 2+ semanas)
pip install -r requirements-dev.txt
pytest                                   # confirme que tudo passa
pip install pip-audit && pip-audit -r requirements.txt
```

## Encerrar o ambiente remoto

1. Pare a aplicação com `Ctrl+C`.
2. Baixe backups/exportações que deseja manter.
3. Opcional: apague os dados em **Configurações → Dados e privacidade → Apagar TODOS os dados**.
4. Em `github.com/codespaces`, no menu `…` do codespace: **Stop codespace** (pausa e mantém os
   arquivos) ou **Delete** (apaga o ambiente e todos os dados que ficaram nele).

Codespaces parados continuam ocupando armazenamento da sua cota até serem apagados.

## Arquitetura

```
app.py                  entrada: senha opcional, navegação, CSS
config.py               configuração por variáveis de ambiente e fuso horário
views/                  as 9 páginas (Streamlit) — não usar o nome pages/ (veja Segurança)
ui/                     componentes de interface compartilhados (Streamlit)
services/               regras de negócio e análises (sem Streamlit)
database/               SQLite: conexão, schema/migrações, repositórios (sem Streamlit)
models/                 vocabulários, padrões e estruturas de dados
assets/style.css        estilo mobile-first (único recurso estático)
tests/                  pytest + testes das páginas com Streamlit AppTest
.streamlit/config.toml  servidor: telemetria desligada, limite de upload, erros genéricos
.devcontainer/          ambiente pronto para GitHub Codespaces
data/                   dados locais (ignorado pelo Git)
```

`services/` e `database/` não importam Streamlit: uma futura API FastAPI pode reutilizá-los
diretamente, trocando apenas a camada `views/` + `ui/`.

## Licença

MIT — veja [LICENSE](LICENSE).
