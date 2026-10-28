# Arquitetura e integrações

## Organização proposta

Aplicação desktop local em camadas: interface → serviços de aplicação → domínio → adaptadores. O domínio define candidatos, decisões, planos e estados sem depender de Qt, JSON de provedores ou detalhes de SQLite.

| Componente | Responsabilidade |
|---|---|
| ui | Telas, modelos de tabela, revisão e eventos de progresso. |
| scanner | Descoberta, deduplicação de caminhos e detecção de contêiner. |
| audio | Inspeção, fingerprint, extração temporária e verificação do áudio. |
| identification | Adaptadores de reconhecedores e resultados normalizados. |
| metadata | Enriquecimento com MusicBrainz e normalização textual. |
| lyrics | Consulta, importação, comparação e validação de letras. |
| resolver | Decisões por campo, conflitos e justificativas. |
| naming | Nome final, restrições do sistema de arquivos, perfil portável e reservas de destinos. |
| tags | Leitores e escritores por contêiner. |
| jobs | Fila persistente, cancelamento, limites e tentativas. |
| changes | Aprovação, backup, commit, recuperação e desfazer. |
| storage | Repositórios SQLite, migrações, cache e diário. |

## Stack proposta

Python 3.11–3.13 para a base atual, HTTPX, platformdirs e Mutagen 1.48.1. A interface opcional usa PySide6-Essentials 6.12.0 (Qt Widgets). Linux é a plataforma prioritária; macOS 15 Sequoia+ é o próximo alvo. O núcleo usa pathlib e bibliotecas portáveis, sem Win32 obrigatório. SQLite com WAL permanece previsto para o item 3. fpcalc, ffprobe e FFmpeg são ferramentas externas da prova de reconhecimento; o inventário não precisa delas.

Credenciais persistentes serão abstraídas por backend do sistema: Secret Service no Linux, Keychain no macOS e Credential Manager quando houver suporte Windows. A prova atual aceita a chave AcoustID somente por variável de ambiente, sem persistência. Builds e empacotamento futuros serão nativos e separados por plataforma; não há garantia de gerar pacote macOS a partir do Linux.

Os itens 1 e 2 implementados usam CLI, testes com pytest, lint com Ruff e configuração TOML. A matriz de CI inclui Ubuntu 24.04, macOS 15 e Windows, com Python 3.11, 3.12 e 3.13. Configurar a matriz não significa que ela já foi executada.

Versões diretas atuais estão fixadas no pyproject.toml e a resolução transitiva está no uv.lock. Executáveis auxiliares são descobertos no PATH ou por caminho configurado e têm suas versões relatadas. Qt e Mutagen foram instalados e testados localmente; a distribuição mantém revisão de licenças pendente.

O inventário está em inventory.py: contratos de leitura, descoberta sem seguir links, deduplicação de pastas e interpretação de tags. A interface fica em ui/: modelo QAbstractTableModel, worker QThread e janela. O worker envia lotes de registros e snapshots de progresso por sinais; somente a thread principal atualiza os widgets/modelo. Os UUIDs do inventário valem para a sessão e ainda não representam uma identidade persistente entre varreduras.

Os itens 6 a 8 acrescentam IdentificationService, MusicBrainz, ProviderCache e resolver. A análise verifica o snapshot, calcula hash, consulta reconhecedores, enriquece até três MBIDs e compara evidências. IdentificationWorker mantém de uma a quatro músicas ativas (padrão duas). Por arquivo, AcoustID seguido de MusicBrainz, ShazamIO e AudD têm ramos independentes. Limitadores são compartilhados por lote; o cache tem acesso SQLite serializado e bloqueio por chave para reaproveitar consultas simultâneas iguais. IdentificationReport contém decisão explicável e hash do arquivo, sem assinatura acústica ou segredos. A política inicial é resolver-v1.

O cache é um SQLite independente em platformdirs/cache/recognition-v1.sqlite3. Não implementa a base de biblioteca/lotes prevista no item 3. Somente respostas normalizadas OK e sem resultado recebem TTL; falhas transitórias permanecem fora do cache. Dados de candidatos são reutilizáveis, mas a decisão é refeita por arquivo, validando seu estado e as opções atuais.

O uso de Mutagen e dos binários auxiliares exige revisar a compatibilidade de licenças. GPLv3 é a hipótese inicial para o código distribuído, sujeita à revisão das dependências efetivamente selecionadas. Nenhuma licença do projeto é concedida por este documento.

## Contratos de domínio

| Contrato | Campos e regras essenciais |
|---|---|
| FileSnapshot | UUID, caminho, diretório original, tamanho, mtime de alta resolução, formato, duração, hash quando necessário e tags lidas. |
| RecordingCandidate | UUID, provedor, ID externo, artistas, título, versão, duração opcional, ISRC/MBID opcionais, score original e evidências. |
| LyricCandidate | UUID, provedor/origem, ID/URL opcional, texto simples, LRC opcional, idioma conhecido, instrumental, metadados disponíveis e data da consulta. |
| Decision | Arquivo, candidatos escolhidos, decisões por campo, confiança de identificação e letra, conflitos, justificativas, autor e versão das regras. |
| ChangePlan | Snapshot esperado, diretório original, nomes atual e final, alterações selecionadas, letra escolhida, destino reservado e estado de aprovação. |
| ProviderResult | Resultado normalizado, candidatos, data, origem cache/rede e erro categorizado quando houver. |
| Operation | Plano, fase persistida, caminhos envolvidos, backup, hashes, tentativas e resultado. |

Ausente é diferente de vazio. Campos não informados não ganham valores inventados. Modelos preservam o texto original e uma forma normalizada para comparação. O score de um fornecedor não é convertido diretamente em probabilidade nem comparado numericamente ao de outro.

## Provedores

| Adaptador | Papel | Política inicial |
|---|---|---|
| AcoustID + fpcalc | Reconhecimento por fingerprint e duração total. | Chave de aplicação; limite herdado do roteiro de até 3 requisições/s, a revalidar. |
| ShazamIO | Segundo reconhecimento por amostras. | Experimental; duração compatível com a versão fixada; até duas amostras úteis por arquivo na configuração inicial proposta. |
| MusicBrainz | Enriquecimento de gravações e lançamentos. | Identificação do cliente; limite inicial herdado de cerca de 1 requisição/s por IP, a revalidar. |
| LRCLIB | Letra simples/sincronizada e indicador instrumental. | Consulta exata e busca; validar versão e duração dos candidatos. |
| lyrics.ovh | Letra por artista e título. | Evidência limitada aos campos efetivamente retornados. |
| Importação local | Letra existente, texto colado ou TXT/LRC. | Não conta como confirmação externa. |
| AudD | Reconhecimento oficial opcional pelo endpoint standard. | Implementado; desativado por padrão, token e limite de consultas por execução obrigatórios para novas chamadas. |
| ACRCloud | Alternativa oficial futura. | Não implementada; desativada. |

Antes de enviar áudio a um provedor, a configuração deve explicar quais dados saem do computador. AcoustID recebe fingerprint e duração; um reconhecedor por amostras pode receber um trecho de áudio. Consultas de letras/metadados enviam termos e identificadores. Não transmitir caminhos locais completos como parâmetros de identificação.

## Erros, limites e cache

Categorias: sem resultado, autenticação, cota/limite, indisponibilidade, rede/timeout, resposta inválida, formato incompatível e cancelamento. Falhas HTTP não equivalem a música desconhecida.

Proposta inicial configurável: timeout de conexão de 10 segundos, limite de 30 segundos por consulta e até três tentativas totais para falhas transitórias. Respeitar Retry-After; usar espera progressiva com variação aleatória. Autenticação inválida suspende o provedor até correção. Não repetir automaticamente erros permanentes. Chamadas pagas consomem orçamento reservado antes do envio, inclusive quando a cobrança de uma tentativa fica incerta.

Um limitador compartilhado controla cada provedor; bloqueios suspendem todos os seus workers. Provedores sem limite validado usam concorrência inicial de uma chamada e intervalo conservador configurável, sujeito à documentação vigente.

Cache positivo proposto: 30 dias; ausência de resultado: 24 horas. Falhas transitórias geram eventos e janela de espera, sem serem armazenadas como ausência. Esses valores são decisões locais iniciais, sujeitos aos termos de retenção do provedor. O usuário pode atualizar uma consulta. Aplicar uma prévia não dispara rede.

## Concorrência e arquivos auxiliares

Separar workers de áudio, rede e escrita. Inicialmente, limitar a dois workers de áudio e um executor de mutações; medir antes de ampliar. Uma mesma identidade de arquivo não pode ter duas operações de escrita simultâneas.

Executáveis auxiliares recebem lista de argumentos sem shell, têm timeout, saída limitada e cancelamento controlado. Temporários de reconhecimento ficam na área temporária do aplicativo; cópias de commit ficam na pasta da música para permitir substituição no mesmo volume. Remover apenas temporários comprovadamente pertencentes a uma operação reconciliada.

Por segurança operacional, a futura varredura não seguirá junctions ou links simbólicos nem modificará arquivos com múltiplos hard links sem revisão específica. A escrita será validada inicialmente em ext4 no Linux e APFS no macOS. Volumes removíveis, rede, NTFS e outros sistemas de arquivos exigem validação própria. A comparação de nomes deve considerar sensibilidade a caixa e normalização Unicode reais do volume. Nesta etapa não existe executor de escrita.
