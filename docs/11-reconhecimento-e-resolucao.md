# Reconhecimento e resolução — itens 6, 7 e 8

## Usar a interface

Feche uma janela aberta antes desta atualização e abra novamente na raiz do projeto:

```powershell
.\.venv\Scripts\python.exe -m afinario gui
```

Em Linux/macOS, preparar também o extra de reconhecimento:

```bash
uv sync --locked --extra gui --extra recognition
uv run --no-sync python -m afinario gui
```

1. Na aba lateral Pastas, adicione as origens e clique em Varrer biblioteca. Essa ação lê apenas os dados locais.
2. A aba Reconhecer mostra os provedores. AcoustID e MusicBrainz vêm habilitados; ShazamIO é opcional e experimental. Marque Permitir ShazamIO para obter a segunda evidência por áudio.
3. Confira a chave e os executáveis em Serviços e ferramentas. Alterações feitas nesse diálogo valem para a sessão, sem gravar a chave em disco.
4. Selecione linhas e clique em Identificar selecionadas, ou use Identificar biblioteca para todos os arquivos legíveis do inventário. O segundo botão inclui registros ocultos pelo filtro textual; a seleção individual respeita as linhas escolhidas.
5. Confira artista/título propostos, identificação e fontes na tabela. As colunas atuais permanecem separadas. A aba Reconhecimento mostra resultados de cada serviço, aliases, MBID, ISRC, scores originais e lançamentos possíveis. A divisão vertical entre tabela e detalhes pode ser arrastada.

Identificar é uma consulta online quando não há cache. AcoustID recebe fingerprint e duração; ShazamIO recebe uma assinatura derivada de um trecho local; MusicBrainz recebe MBIDs. Arquivos, capas, letras existentes, nomes e diretórios não são alterados. As propostas agora podem ser revisadas e aprovadas por campo em Revisar e aprovar, conforme [Credenciais, letras e aprovação](14-credenciais-letras-e-aprovacao.md). Aplicação em tags/nomes permanece futura.

## Configuração e diagnóstico

O comando gui e o executável afinario-desktop carregam `afinario.local.toml` da pasta atual quando existe. Configuração explícita também é aceita: `python -m afinario --config caminho.toml gui`. O diálogo de serviços permite ajustar fpcalc, FFmpeg, ffprobe e chave AcoustID sem reiniciar a janela.

A chave vem do ambiente, com fallback para a variável persistente do usuário no Windows, ou pode ser informada no diálogo com exibição mascarada. Salvar configurações grava as credenciais no cofre nativo do usuário, fora do banco e do repositório. Não incluir credenciais em TOML, relatórios ou código.

AcoustID precisa de fpcalc para novas consultas. ShazamIO precisa do extra recognition e FFmpeg; ffprobe é usado quando a duração local ainda não é conhecida. O MusicBrainz não conta como reconhecedor independente. Suas consultas usam o User-Agent configurado em network.user_agent; configure uma identificação significativa e contato real antes de uma distribuição pública.

## Fluxo implementado

Por arquivo: comparar tamanho e mtime com o inventário; calcular SHA-256; consultar AcoustID por fingerprint/duração total; reconhecer até dois trechos úteis com ShazamIO quando autorizado; enriquecer até três MBIDs distintos; comparar candidatos; verificar novamente tamanho, mtime e hash; publicar a proposta ou motivo de revisão.

Atualização em 28/10/2026: músicas e provedores passam a executar em paralelo, conforme [AudD e paralelismo](12-audd-e-paralelismo.md). O lote compartilha limites por serviço, tentativas limitadas e tratamento de Retry-After. Cada serviço tem categorias distintas para ausência, autenticação, limite, rede, resposta inválida e erro local de áudio. Uma fonte em pausa não impede consultar as demais. AudD pode atuar como fonte independente no lugar de ShazamIO; a comparação avalia todas as fontes habilitadas, inclusive uma terceira fonte discordante.

Cancelar interrompe etapas seguintes, esperas de quota e processos locais. Uma requisição HTTP em andamento pode precisar chegar ao timeout antes de encerrar. Resultados de arquivos já concluídos permanecem visíveis. Fechar a janela solicita cancelamento e aguarda o worker sem congelar o processamento de eventos. Pausa/retomada persistente de lotes continua no escopo futuro.

## Cache

O arquivo `recognition-v1.sqlite3` fica no diretório de cache retornado por platformdirs. É separado do banco library.sqlite3 da biblioteca, conforme [Persistência](13-persistencia-da-biblioteca.md). Candidatos e propostas da biblioteca permanecem disponíveis após fechar/reabrir, mesmo sem o cache de consultas. Se não for possível abri-lo, o lote usa cache em memória e registra a ocorrência.

Chaves de consulta são hashes versionados por provedor: reconhecimento usa o hash completo do arquivo; metadados usam MBID. Não são armazenadas chaves de acesso, fingerprints, trechos, letras ou respostas brutas. Candidatos, aliases e alternativas de lançamento são persistidos normalizados. Os resultados não tornam dois arquivos iguais por identidade acústica.

TTL positivo: 30 dias. Ausência de correspondência: 24 horas. Falhas transitórias e autenticação não recebem cache. A opção Atualizar consultas ignora resultados existentes e permite nova consulta. Respostas válidas armazenadas podem ser reutilizadas sem rede, inclusive sem a chave AcoustID atual; a fonte ainda precisa estar selecionada. A decisão é sempre recalculada, não recuperada cegamente do cache.

## Política resolver-v1

| Evidência | Resultado |
|---|---|
| Dois reconhecedores concordam em artista/título ou aliases cadastrados, sem conflito relevante. | Fontes concordam; proposta de artista e título. |
| Só um reconhecedor retorna candidato utilizável. | Confirmação incompleta; proposta exige revisão. |
| Candidatos próximos, evidência fraca, artistas/títulos/IDs ou versões incompatíveis. | Revisão necessária, sem campos propostos automaticamente. |
| Duração de candidato incompatível com a duração do arquivo. | Revisão necessária. |
| Todas as fontes consultadas retornam sem resultado. | Não identificada. |
| Não há resultado utilizável por falha de serviço/configuração. | Consulta bloqueada ou falhou, com motivo por fonte. |
| Arquivo mudou desde o inventário ou durante a análise. | Arquivo alterado; refazer varredura. |

Normalizar caixa, pontuação, caracteres de largura diferente e acentos latinos. Preservar sinais significativos de outros alfabetos, inclusive dakuten japonês. Títulos em idiomas diferentes só são aproximados por aliases conhecidos; não usar traduções inventadas, recortes arbitrários de título ou tags existentes para vencer divergências do áudio.

Agrupar resultados AcoustID ligados ao mesmo MBID antes de avaliar ambiguidade. Como guardas provisórias, um score AcoustID abaixo de 0,8 ou uma distância inferior a 0,05 entre gravações concorrentes exige revisão. A tolerância de duração é o maior entre 3 segundos e 2% da duração local. Marcadores como live, remix, instrumental, cover e TV size são confrontados de forma conservadora. ISRCs incompatíveis também exigem revisão.

Esses limites são heurísticas iniciais, sem calibração estatística nem automação de escrita. Scores de fornecedores diferentes não são comparados entre si. A concordância é uma proposta explicável e não uma garantia de gravação/edição correta. Álbum, ano e faixa não são preenchidos pelo primeiro lançamento encontrado: alternativas permanecem nos detalhes.

## Evidências

Validação no host Windows, Python 3.11.9, em 27/10/2026 (America/Cuiaba). A CI Linux/macOS está configurada e ainda precisa ser executada nessas plataformas.

- O fluxo completo foi executado pela janela sobre `01 - Samurai Heart (Some Like It Hot!!).mp3`. AcoustID, ShazamIO e MusicBrainz responderam; o resolvedor conciliou os títulos por alias e exibiu Fontes concordam, artista SPYAIR. MusicBrainz retornou 21 lançamentos possíveis, sem seleção automática de álbum/ano.
- A faixa foi reanalisada com o transporte HTTP substituído por uma falha obrigatória caso houvesse rede. Todos os resultados vieram do cache e a decisão continuou concordante.
- `7!! - Lovers.mp3`, sem tags de artista/título, retornou candidatos pelos serviços. Duração local de 228,26 s e duração de catálogo de 222 s excederam a tolerância; a janela mostrou Revisão necessária e preservou alternativas em detalhes. Não foi escolhida uma versão automaticamente.
- Nos dois arquivos reais, SHA-256 antes/depois confirmou bytes intactos. A primeira prova verificou também tamanho e mtime.

Evidências locais em reports/, ignoradas pelo Git: `identification-gui-20261028T025413Z.json`, `identification-cache-offline.json`, `identification-untagged.json` e `afinario-identification.png`. Timestamps de relatório usam UTC.

Os testes determinísticos cobrem aliases multilíngues, versões, duração, candidatos próximos, duplicatas de fingerprint, independência das fontes, ausência versus rede, ISRC, TTL, cache corrompido, reutilização offline, refresh, mudança externa, cancelamento de processos, seleção na tabela e continuidade da interface. Não dependem dos serviços online.

Resultado da suíte: **132 testes aprovados e um pulado** por restrição local para criar symlinks, com lint/formatação aprovados e wheel gerado. O teste de symlinks deve executar nas plataformas com permissão apropriada.

Documentação primária usada para a integração: [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API), [limites de acesso](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting) e [conceito de gravação](https://musicbrainz.org/doc/Recording). Uma gravação pode aparecer em vários lançamentos; essa relação não determina a edição do arquivo local.

Atualização posterior: o [diagnóstico e player](15-diagnostico-e-player.md) detalha os rótulos de bloqueio, a recusa de chave AcoustID com HTTP 400, o histórico de propostas divergentes e a reprodução local para revisão.
