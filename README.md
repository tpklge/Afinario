# Afinário

**Sua biblioteca musical em harmonia.**

Afinário é um organizador local de músicas com desenvolvimento prioritário para Linux e portabilidade planejada para macOS 15 Sequoia ou superior. Combina a ideia de afinar com a de inventariar: reconhecer gravações pelo áudio, revisar metadados, encontrar letras e dar nomes consistentes aos arquivos.

**Situação: itens 1, 2, 4, 5, 6, 7 e 8 implementados no escopo inicial.** A interface inventaria arquivos, reconhece pelo áudio em AcoustID, ShazamIO ou AudD e consulta MusicBrainz. O processamento aceita músicas e provedores em paralelo, com cotas compartilhadas e limite de consultas pagas. Há cache em disco; a biblioteca e suas decisões continuam em memória (item 3 ainda pendente). Letras na interface, aplicação de mudanças e validação prática em Linux/macOS são etapas posteriores. A disponibilidade de marca e domínio do nome Afinário não foi pesquisada.

## Executar a base

Requer Python 3.11–3.13. A implementação executa diretamente no sistema operacional, sem Wine. Python é interpretado; não há promessa de binário autossuficiente nesta etapa. A interface desktop usa Qt Widgets, sem navegador.

Linux/macOS, com uv 0.13.6 instalado:

```bash
uv sync --locked --extra gui --extra recognition
uv run --no-sync python -m afinario gui
```

No Windows, com o ambiente já preparado: `.\.venv\Scripts\python.exe -m afinario gui`. É possível passar pastas como argumentos para pré-carregar a lista de origens.

Para inventário sem interface: `uv run --no-sync python -m afinario scan '/caminho/das/musicas'`. Funciona offline, sem chave e sem FFmpeg. O extra `recognition` continua opcional para a prova de reconhecimento. Consulte o [guia de desenvolvimento](docs/08-desenvolvimento.md) e o [guia do inventário](docs/10-inventario-e-interface.md).

Após varrer, abra a aba lateral **Reconhecer**, marque **Permitir ShazamIO (experimental)** se desejar a segunda fonte e clique em **Identificar selecionadas** ou **Identificar biblioteca**. A tabela separa os campos atuais dos propostos; os detalhes mostram fontes, alternativas e motivos de revisão. Configure a chave AcoustID e os executáveis em **Serviços e ferramentas…**. Veja o [guia de reconhecimento](docs/11-reconhecimento-e-resolucao.md).

Para o plano AudD, informe o token mascarado em **Serviços e ferramentas…**, marque **Usar AudD (plano pago)** e escolha o limite de novas consultas da execução (comece com 1 para testar). O padrão 0 não envia consultas pagas. AudD pode substituir ShazamIO; não exige o extra recognition. [Guia AudD e paralelismo](docs/12-audd-e-paralelismo.md).

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

## Repositório de destino

O destino de código é [tpklge/Afinario](https://github.com/tpklge/Afinario), configurado como origin local. Em 28/10/2026, o usuário autorizou o primeiro envio e informou que o repositório permanece privado. Credenciais, configurações locais, ferramentas baixadas, relatórios e ambientes virtuais ficam excluídos pelo .gitignore.

## Como usar estes documentos

Ler os requisitos antes de definir tarefas técnicas. As regras de preservação e recuperação são condições de entrega, inclusive para a primeira versão utilizável. Cada etapa do plano deve produzir evidências de seus critérios de aceitação.

Esta documentação foi preparada em 27/10/2026 a partir de `roteiro_app_musicas_windows11.md`, fornecido pelo usuário, e atualizada conforme autorização para os itens 1, 2 e 4 a 8. O pedido de priorizar Linux e macOS substitui a plataforma inicial Windows do roteiro. Nenhuma conta foi criada pelo agente e nenhum provedor pago foi ativado.

As verificações externas desta implementação estão registradas no documento de validação inicial. As demais premissas do roteiro, especialmente distribuição e licenças da futura stack completa, ainda precisam ser verificadas antes da adoção ou publicação.
