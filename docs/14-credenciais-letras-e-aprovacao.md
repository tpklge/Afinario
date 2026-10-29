# Credenciais locais, letras e aprovação por campo

Entrega de 28/10/2026 para macOS e Windows 11, com Secret Service como backend adicional no Linux. Esta seção descreve a entrega inicial de revisões. A aplicação com backup, renomeação e restauração foi acrescentada em [Planejamento, aplicação e restauração](16-planejamento-aplicacao-e-restauracao.md).

## Configurar uma vez neste computador

Em Reconhecer → Serviços e ferramentas…, informe chave AcoustID e token AudD e clique em Salvar configurações. O diálogo grava os segredos no cofre do sistema e os parâmetros públicos na biblioteca. Falha de acesso ao cofre mantém o diálogo aberto com o motivo, sem gravar um arquivo alternativo de senhas.

| Sistema | Armazenamento de segredos |
|---|---|
| macOS | Keychain do usuário |
| Windows 11 | Gerenciador de Credenciais, backend WinVault |
| Linux | Secret Service, quando disponível na sessão |

A integração usa [keyring](https://keyring.readthedocs.io/en/stable/) com backend nativo escolhido explicitamente. O serviço é Afinario e a entrada é provider-credentials-v1. As duas credenciais são substituídas em uma única entrada para evitar um par parcialmente gravado. O aplicativo não aceita backends de arquivos em texto simples.

Ao abrir novamente, valores salvos prevalecem sobre variáveis antigas do ambiente. Sem uma entrada salva, continuam disponíveis AFINARIO_ACOUSTID_KEY e AFINARIO_AUDD_TOKEN, incluindo o fallback do registro do usuário no Windows. Deixar um campo vazio e salvar desativa aquela credencial, mesmo que exista uma variável antiga.

O cofre pertence ao usuário do sistema e não acompanha código, GitHub ou o banco da biblioteca. Cada pessoa e computador configura suas próprias chaves. TOML, preferências SQLite, relatórios e repr de Settings excluem segredos. Mensagens são sanitizadas. O .gitignore também exclui .env e variantes, arquivos locais de credenciais e bancos/sidecars SQLite.

Doctor e probe leem as credenciais salvas; o relatório de diagnóstico informa apenas se cada serviço está configurado. Nenhum teste determinístico consulta as credenciais reais do usuário.

## Serviços de letras pesquisados

Pesquisa em fontes primárias, em 28/10/2026:

| Serviço | Acesso e conteúdo | Decisão nesta entrega |
|---|---|---|
| [LRCLIB](https://lrclib.net/docs) | API pública sem chave obrigatória; letras simples, LRC, duração e indicação instrumental. Pede identificação do cliente e consultas sequenciais com intervalo. | Integrado. A busca preserva alternativas e confere artista, título e duração. Intervalo local de 0,5 s; respeita 429/Retry-After. |
| [lyrics.ovh](https://github.com/NTag/lyrics.ovh) | Endpoint público por artista/título, texto ou 404. A resposta não traz duração nem identidade. O projeto informa que consulta LRCLIB antes de outras fontes. | Integrado. Coincidência entre textos não é anunciada como confirmação de catálogos independentes. |
| [Musixmatch](https://www.postman.com/musixmatch-dev/musixmatch-apis/overview) | A coleção oficial orienta escolher um plano e usar chave própria; o [SDK oficial](https://github.com/musixmatch/musixmatch-sdk) exige observar termos da API. | Opção comercial pesquisada. As páginas diretas de documentação/preços não puderam ser lidas nesta pesquisa; não foram inventados valores, cotas ou direitos de armazenamento. |
| [LyricFind](https://www.lyricfind.com/products/lyric-display) | Licenciamento de exibição em texto, linha a linha e palavra a palavra; a página encaminha para contato comercial. | Opção comercial pesquisada. Integração depende de acesso contratado e condições de cache, atribuição e incorporação de letras. |

As duas opções públicas já estão disponíveis na interface sem cadastrar contas. As opções comerciais não são acionadas nem recebem credenciais nesta versão. Antes de implementar um contrato comercial, é preciso confirmar se ele permite o uso pretendido em biblioteca local, especialmente retenção e incorporação em arquivos; acesso público à API por si só não define direitos de redistribuição do conteúdo.

## Buscar, importar e comparar

1. Varrer a biblioteca e, quando necessário, identificar o áudio.
2. Selecionar uma música e abrir Revisar e aprovar. A aba Metadados permite escolher uma identificação alternativa, editar artista/título e escolher álbum/data explicitamente.
3. Na lateral Letras, escolher fontes e modo. Completo consulta todas as fontes habilitadas; Rápido tenta a segunda quando a primeira não fornece resultado utilizável. Buscar letras selecionadas e Buscar letras da biblioteca respeitam esse modo.
4. Em Revisar e aprovar → Letras e diferenças, conferir a consulta, resultados e candidatos. A seleção mostra atual/proposto e diferenças para letra simples e LRC separadamente.
5. Ler embutida funciona offline. Importar TXT/LRC e Colar letra adicionam candidatos locais com procedência; importações são limitadas a um arquivo musical selecionado por vez. TXT aceita UTF-8, UTF-8 com BOM e UTF-16 com BOM; LRC exige timestamps válidos. Limite de importação: 2 MB.

As músicas não são enviadas às fontes de letras: a consulta usa artista/título. A análise lê letras embutidas de MP3/ID3, M4A, FLAC, Vorbis e Opus; SYLT com tempo em milissegundos é representada como LRC. LRC não substitui automaticamente letra simples.

Candidatos de busca incompatíveis ficam disponíveis como alternativas, com motivos, mas são excluídos da sugestão. A tolerância inicial de duração é o maior entre 3 s e 2% da duração local. Textos diferentes, tradução ou indicação instrumental conflitante pedem revisão. Ausência, instrumental e indisponibilidade são estados diferentes. A identificação musical e a avaliação da letra continuam separadas.

Letra existente é preservada por padrão. Escolher outro texto não autoriza a substituição: é necessário marcar Autorizar substituição da letra existente e aprovar o campo correspondente. Edições de artista/título retiram a proposta anterior de letra; uma letra remota pesquisada para outra identidade precisa de nova busca antes da aprovação.

Resultados e candidatos ficam na biblioteca; o cache de consultas de letras usa lyrics-v1.sqlite3, separado do cache de reconhecimento. TTL positivo: 30 dias; ausência: 24 horas; falhas não recebem cache. Atualizar letras ignora o cache. Importar outro candidato ou reler a letra embutida mantém alternativas anteriores quando pertencem à mesma consulta.

## Aprovação por campo

Campos: artista, título, álbum, artista do álbum, faixa, disco, data/ano, gênero, nome do arquivo, letra simples e letra sincronizada. Os campos podem ser escolhidos independentemente; metadados podem ser aprovados mesmo sem letra.

Nenhum campo começa aprovado. Marcar os campos e clicar em Salvar aprovação dos campos marcados registra a revisão exata, data UTC, origem dos valores e versão da política review-v1. Uma nova edição invalida as aprovações anteriores e salva o rascunho automaticamente; fechar a janela aguarda essa gravação.

Novas evidências invalidam aprovações antigas, preservando edições explícitas quando o snapshot do arquivo é o mesmo. Alterar o arquivo exige nova revisão. Revisões de outra janela são protegidas por controle de versão; uma revisão antiga não sobrescreve silenciosamente uma nova.

O nome aprovado é somente um basename, preserva a extensão e passa por validação preliminar para macOS/Windows: separadores, caracteres proibidos e nomes reservados são recusados. Planejamento de colisões e execução de renomeações estão disponíveis na aba Aplicar e restaurar. Aprovar grava escolhas na biblioteca; não modifica tags, nomes ou bytes de áudio.

## Banco e validação

A migração 3 acrescenta lyric_analyses e review_revisions às versões anteriores, com backup consistente antes da atualização. Reconhecimento, letras e revisões ficam vinculados ao snapshot e ao contexto de evidências.

A validação local inclui suíte determinística com cofres simulados, cache, modos de consulta, falhas, letras embutidas por formato, importações, conflitos, aprovação seletiva, invalidação, concorrência e reabertura. Há também prova de janela Cocoa nativa: revisão manual, letra local, aprovação de título/letra, reabertura e preservação dos bytes do áudio.

Resultado final em macOS arm64/Python 3.11: **246 testes aprovados**, com lint, formatação e instalação pelo lock verificados. A migração de uma biblioteca v2 com inventário e reconhecimento também foi testada, preservando os dados anteriores.

O Keychain real do macOS foi validado com uma entrada sintética de serviço único, lida e removida em seguida; nenhuma credencial do usuário foi consultada nessa prova. Uma consulta pública separada por Coldplay/Yellow retornou 20 candidatos LRCLIB e um candidato lyrics.ovh, uma tentativa por fonte, sem publicar textos de letras em relatórios. Isso demonstra resposta dos serviços, não acerto de versão ou cobertura geral.

Windows 11 mantém o adaptador nativo e testes de seleção do backend; a prova em um equipamento Windows 11 real continua pendente. Nenhum serviço pago de letras foi ativado.
