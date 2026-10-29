# Afinário

**Sua biblioteca musical em harmonia.**

Afinário é um organizador local de músicas com desenvolvimento em macOS e Windows 11, mantendo Linux como plataforma adicional. O alvo macOS é a versão 15 Sequoia ou superior. Combina a ideia de afinar com a de inventariar: reconhecer gravações pelo áudio, revisar metadados, encontrar letras e dar nomes consistentes aos arquivos.

**Situação: itens 1 a 8 do roteiro original implementados no escopo inicial.** A interface inventaria arquivos, reconhece pelo áudio em AcoustID, ShazamIO ou AudD e consulta MusicBrainz. O processamento aceita músicas e provedores em paralelo, com cotas compartilhadas e limite de consultas pagas. Há cache em disco e biblioteca SQLite com restauração de inventário, propostas, candidatos, lotes e preferências. Letras, aprovação por campo, prévia de nomes, aplicação com backup e restauração estão implementadas no escopo inicial. Novos reconhecimentos com concordância entre pelo menos duas fontes independentes podem renomear e preencher artista/título automaticamente, com backup. Letras ausentes podem ser buscadas e aplicadas quando a identidade e as tags atuais estão validadas; divergências e outros campos continuam para revisão. Há pausa/retomada persistente de lotes e relatórios CSV/JSON. Veja a [persistência da biblioteca](docs/13-persistencia-da-biblioteca.md). A homologação prática em Windows 11 e nas arquiteturas alvo continua necessária. A disponibilidade de marca e domínio do nome Afinário não foi pesquisada.

## Executar a base

Requer Python 3.11–3.13. A implementação executa diretamente no sistema operacional, sem Wine. Python é interpretado; não há promessa de binário autossuficiente nesta etapa. A interface desktop usa Qt Widgets, sem navegador.

Linux/macOS, com uv 0.13.6 instalado:

```bash
uv sync --locked --extra gui --extra recognition
uv run --no-sync python -m afinario gui
```

No Windows, com o ambiente já preparado: `.\.venv\Scripts\python.exe -m afinario gui`. É possível passar pastas como argumentos para pré-carregar a lista de origens. Para baixar, preparar as dependências e testar os recursos, siga o [guia de teste no Windows 11](docs/18-teste-no-windows-11.md). O instalador com dependências incluídas ainda não foi implementado.

Para inventário sem interface: `uv run --no-sync python -m afinario scan '/caminho/das/musicas'`. Funciona offline, sem chave e sem FFmpeg. O extra `recognition` continua opcional para a prova de reconhecimento. Consulte o [guia de desenvolvimento](docs/08-desenvolvimento.md) e o [guia do inventário](docs/10-inventario-e-interface.md).

Após varrer, abra a aba lateral **Reconhecer**, marque **Permitir ShazamIO (experimental)** se desejar a segunda fonte e clique em **Identificar selecionadas** ou **Identificar biblioteca**. A tabela separa os campos atuais dos propostos; os detalhes mostram fontes, alternativas e motivos de revisão. Configure a chave AcoustID e os executáveis em **Serviços e ferramentas…**. As credenciais são salvas no cofre do sistema para este usuário e computador, fora do GitHub. Veja o [guia de reconhecimento](docs/11-reconhecimento-e-resolucao.md).

Para o plano AudD, informe o token mascarado em **Serviços e ferramentas…**, marque **Usar AudD (plano pago)** e escolha o limite de novas consultas da execução (comece com 1 para testar). O padrão 0 não envia consultas pagas. AudD pode substituir ShazamIO; não exige o extra recognition. [Guia AudD e paralelismo](docs/12-audd-e-paralelismo.md).

Para conferir pelo ouvido, selecione uma música e use **Reproduzir** no player abaixo dos detalhes (ou dê dois cliques na linha). Há pausa, parada, posição e volume; selecionar outra faixa interrompe a anterior sem iniciar a próxima. O player usa somente o arquivo local. Consultas encerradas com falha ou bloqueio mostram o motivo, e identificações diferentes entre buscas do mesmo áudio ficam para revisão com a proposta anterior disponível. Veja [Diagnóstico e player](docs/15-diagnostico-e-player.md).

Para gravar alterações, use **Aplicar e restaurar**: gere a prévia, confira os destinos e aplique os itens prontos. A mesma aba configura a renomeação, tags e letras automáticas e a pasta de backups, além de permitir restaurar operações concluídas. Em **Lotes e relatórios**, retome lotes pausados ou interrompidos e exporte a biblioteca ou músicas selecionadas em CSV/JSON. **Pausar lote** aguarda o trabalho em andamento chegar a um ponto seguro. Veja [Planejamento, aplicação e restauração](docs/16-planejamento-aplicacao-e-restauracao.md).

## Resultado esperado

O usuário seleciona pastas, analisa músicas, compara propostas e aplica alterações escolhidas com backup e possibilidade de desfazer. Os arquivos permanecem nas respectivas pastas de origem. A ferramenta não transcodifica o áudio.

## Documentação

1. [Visão e requisitos](docs/01-visao-e-requisitos.md): escopo, regras e critérios de aceitação.
2. [Arquitetura e integrações](docs/02-arquitetura-e-integracoes.md): componentes, contratos, provedores e execução.
3. [Modelo de dados e estados](docs/03-dados-e-estados.md): persistência, cache, fila e rastreabilidade.
4. [Escrita e recuperação](docs/04-escrita-e-recuperacao.md): nomes, integridade, backup, commit e desfazer.
5. [Interface e experiência](docs/05-interface-e-experiencia.md): telas, ações e mensagens.
6. [Implementação e validação](docs/06-plano-e-validacao.md): entregas, testes, distribuição e decisões pendentes.
7. [Decisões e referências](docs/07-decisoes-e-referencias.md): fundamentos e relação com o roteiro recebido.
8. [Desenvolvimento e execução](docs/08-desenvolvimento.md): instalação, comandos, configurações e organização do código.
9. [Validação inicial](docs/09-validacao-inicial.md): evidências dos itens 1 e 2 e próximos bloqueios.
10. [Inventário e interface](docs/10-inventario-e-interface.md): itens 4 e 5, uso e evidências de validação.
11. [Reconhecimento e resolução](docs/11-reconhecimento-e-resolucao.md): itens 6, 7 e 8, configuração, cache, regras e validação.
12. [AudD e paralelismo](docs/12-audd-e-paralelismo.md): token, orçamento, concorrência e limites por fonte.
13. [Persistência da biblioteca](docs/13-persistencia-da-biblioteca.md): SQLite, migrações, restauração, preferências e compatibilidade macOS/Windows 11.
14. [Credenciais, letras e aprovação](docs/14-credenciais-letras-e-aprovacao.md): cofre nativo, fontes públicas/comerciais, TXT/LRC, comparação e aprovação por campo.
15. [Diagnóstico e player](docs/15-diagnostico-e-player.md): bloqueios, chave AcoustID, limite AudD, divergências entre buscas e reprodução local.
16. [Planejamento, aplicação e restauração](docs/16-planejamento-aplicacao-e-restauracao.md): nomes, concordância automática, campos aprovados, backups, recuperação e desfazer.

17. [Automação, lotes e relatórios](docs/17-automacao-lotes-e-relatorios.md): tags e letras automáticas, aprovações maiores, pausa, retomada e exportação.
18. [Teste no Windows 11](docs/18-teste-no-windows-11.md): preparação pelo código-fonte, ferramentas, credenciais e roteiro de homologação.

## Repositório de destino

O destino de código é [tpklge/Afinario](https://github.com/tpklge/Afinario), configurado como origin local. Em 28/10/2026, o usuário autorizou o primeiro envio e informou que o repositório permanece privado. Credenciais, configurações locais, ferramentas baixadas, relatórios e ambientes virtuais ficam excluídos pelo .gitignore.

## Como usar estes documentos

Ler os requisitos antes de definir tarefas técnicas. As regras de preservação e recuperação são condições de entrega, inclusive para a primeira versão utilizável. Cada etapa do plano deve produzir evidências de seus critérios de aceitação.

Esta documentação foi preparada em 27/10/2026 a partir de `roteiro_app_musicas_windows11.md`, fornecido pelo usuário, e atualizada com as entregas dos itens 1 a 8 do roteiro original. A orientação atual mantém macOS e Windows 11 como alvos de desenvolvimento; as decisões anteriores de priorizar Linux permanecem apenas como histórico do plano. Nenhuma conta foi criada pelo agente e nenhum provedor pago foi ativado.

As verificações externas desta implementação estão registradas no documento de validação inicial. As demais premissas do roteiro, especialmente distribuição e licenças da futura stack completa, ainda precisam ser verificadas antes da adoção ou publicação.
