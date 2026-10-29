# Persistência da biblioteca — item 1 da revisão de implementação

Implementado em 28/10/2026, em macOS, mantendo o código compatível com Windows 11 e Linux. Esta entrega corresponde ao antigo item 3 do roteiro original: banco da biblioteca. Usa apenas sqlite3 da biblioteca padrão, pathlib e platformdirs; não introduz dependência de APIs exclusivas de um sistema.

## Comportamento

- Abrir a janela restaura o último inventário, resultados de reconhecimento, motivos das decisões, candidatos, fontes, ocorrências e preferências, sem consultas online nem nova leitura das músicas.
- Uma nova varredura mantém o UUID do mesmo caminho. Se o snapshot de tamanho, mtime, tags e demais dados lidos for igual, reutiliza o snapshot e mantém a proposta. Alterações detectadas criam um snapshot imutável e deixam propostas anteriores apenas no histórico interno.
- Varreduras e reconhecimentos possuem lotes com opções congeladas, início/fim em UTC, estado e resumo. Cada resultado é confirmado no banco antes de aparecer na tabela.
- O último inventário determina os arquivos exibidos; arquivos de inventários anteriores e suas evidências permanecem no banco. Uma varredura vazia exibe uma biblioteca vazia sem apagar esse histórico.
- Cancelamento mantém os resultados já confirmados. Após uma queda, a parte confirmada da última varredura pode ser reaberta; a interface informa que ela ficou incompleta. Abrir outra janela não altera o estado de um lote que pode pertencer a outro processo.
- A CLI scan também grava na biblioteca e seus relatórios usam os UUIDs persistentes. Doctor e probe mantêm seu comportamento anterior.

As decisões do resolvedor continuam separadas das aprovações do usuário. A migração 3 acrescenta letras e revisões aprovadas por campo, conforme [Credenciais, letras e aprovação](14-credenciais-letras-e-aprovacao.md). A migração 4 acrescenta planos, operações, diário, reservas e evidências após alterações, conforme [Aplicação e restauração](16-planejamento-aplicacao-e-restauracao.md). A migração 5 acrescenta `task_batches` e `task_items`, checkpoints por música, pausa/retomada e a contagem persistente de reservas AudD, conforme [Automação, lotes e relatórios](17-automacao-lotes-e-relatorios.md).

## Local dos dados

O arquivo library.sqlite3 reside em app_paths()["data"], fora do repositório:

| Sistema | Local padrão |
|---|---|
| macOS | ~/Library/Application Support/afinario/library.sqlite3 |
| Windows 11 | %LOCALAPPDATA%\afinario\library.sqlite3 |
| Linux | $XDG_DATA_HOME/afinario/library.sqlite3, normalmente ~/.local/share/afinario/library.sqlite3 |

O comando doctor informa a pasta efetiva de dados. O cache recognition-v1.sqlite3 continua separado na pasta de cache. Apagar esse cache não apaga a biblioteca, os candidatos ou as decisões já registradas.

Cada sistema usa seu próprio banco. Desenvolver o mesmo repositório no Windows e no macOS não compartilha automaticamente os bancos locais. Copiar um banco não remapeia caminhos, volumes ou letras de unidade.

## Preferências e credenciais

São salvos pastas, recursividade, formatos, filtro textual, ferramentas e parâmetros de rede/processamento. A gravação ocorre no início de varreduras/reconhecimentos e ao fechar a janela; não há escrita do banco na thread da interface.

TOML explícito ou afinario.local.toml tem precedência sobre parâmetros de serviços salvos. Pastas passadas à GUI substituem as origens salvas para a sessão. Caminhos de executáveis só são restaurados automaticamente no mesmo sistema operacional em que foram salvos.

Chave AcoustID e token AudD agora podem ser salvos no cofre nativo do sistema, fora da biblioteca e do GitHub; o ambiente continua como fallback quando não há configuração salva. A serialização de configurações aceita uma lista explícita de campos sem credenciais. Mensagens de serviços e motivos de decisão passam pelo sanitizador antes da persistência. Não são armazenados fingerprints, amostras de áudio ou respostas HTTP brutas.

As seleções de provedores são restauradas; numa biblioteca nova, AudD e ShazamIO começam desmarcados. Abrir a aplicação não inicia chamadas online nem aplica propostas antigas. A política de renomeação após novos reconhecimentos e a pasta de backups também são persistidas.

## Esquema e concorrência

Versão atual: 5, em PRAGMA user_version. schema_migrations registra as versões aplicadas e os instantes. A migração 1 cria inventário, snapshots, lotes, itens, ocorrências e preferências; a migração 2 acrescenta reconhecimentos, decisões, resultados e candidatos; a migração 3 acrescenta análises de letras e revisões por campo.

Chaves estrangeiras ficam habilitadas por conexão, o diário usa WAL e synchronous=FULL. As transações de gravação são curtas e usam BEGIN IMMEDIATE. Cada worker abre e fecha sua própria conexão na mesma thread; conexões SQLite não são compartilhadas com as threads de provedores.

O reconhecimento fica vinculado ao snapshot analisado. Se outra execução atualizar esse snapshot, o resultado antigo é recusado em vez de ser associado silenciosamente ao novo arquivo. Datas usam UTC. Caminhos preservam Unicode e sua grafia; a chave de comparação no Windows considera separadores e caixa, enquanto o macOS preserva caixa para não colapsar arquivos distintos em APFS sensível a caixa. Hard links continuam sendo itens separados por caminho.

O SHA-256 calculado pelo reconhecimento é persistido na identificação vinculada ao snapshot. O inventário não calcula hash integral por conta própria; ao reconhecer, o serviço existente revalida tamanho, mtime e hash antes/depois das consultas.

## Migração e recuperação do banco

Antes de atualizar uma biblioteca existente, o aplicativo cria library.pre-vN-UUID.sqlite3 na mesma pasta. A cópia usa SQLite Backup, incluindo páginas já confirmadas no WAL, e passa por quick_check. Falha na cópia impede a migração. A atualização de esquema é uma transação: falhas revertem o esquema e a versão.

Banco criado por versão futura, arquivo de outro aplicativo ou banco ilegível não é recriado nem substituído por um vazio. A interface mostra o erro e o caminho em Ocorrências e bloqueia novas análises até o acesso ser corrigido.

Para restaurar uma cópia de migração:

1. Fechar todas as instâncias do Afinário.
2. Preservar o banco atual e seus arquivos -wal/-shm juntos em uma pasta separada para diagnóstico.
3. Copiar a cópia validada escolhida para library.sqlite3, sem reutilizar os sidecars do banco anterior.
4. Reabrir o aplicativo; se necessário, ele fará novamente a migração a partir da cópia.

Essas cópias protegem migrações da biblioteca; não substituem backup regular dos dados do usuário nem são backups de músicas.

## Validação

A suíte determinística inclui reabertura em outro processo sem rede, round-trip Unicode, UUID estável, invalidação por snapshot, preservação de histórico, rollback de resultados, cancelamento, configurações sem segredos, concorrência e migração com dados no WAL. Também verifica falha de backup/migração e recusa de bancos futuros, desconhecidos ou corrompidos.

Os testes Qt cobrem fechar/reabrir, reaproveitar propostas sem novas consultas, mudança externa, preferências, precedência de configuração, ocorrências, inventário parcial, falha de persistência e responsividade durante abertura/encerramento. A suíte usa pastas de dados/cache isoladas e áudio sintético; nenhum arquivo musical do usuário é alterado e nenhum provedor é consultado.

Validação local em macOS 26.7 arm64, Python 3.11.16 e Qt/PySide6 6.12.0: **191 testes aprovados**, lint e formatação aprovados. Além da suíte offscreen, uma janela Cocoa nativa varreu uma fixture, fechou, reabriu e confirmou UUID, origens restauradas e bytes do áudio preservados.

A matriz existente de CI mantém macOS, Windows e Linux; ela não foi executada remotamente nesta sessão. A execução local em macOS não comprova homologação em um Windows 11 real. Essa prova continua necessária no equipamento Windows.
