# Interface e experiência

## Jornada principal

Adicionar pastas → inventariar → analisar → revisar propostas → selecionar ações → aplicar → conferir resultado. A página inicial explica que a análise prepara sugestões e que os arquivos permanecem em suas pastas.

## Telas

| Tela | Conteúdo e ações |
|---|---|
| Pastas | Origens, recursividade, filtros, contagem e varredura. Indicar pastas inacessíveis sem descartar as demais. |
| Biblioteca | Seleção, pasta, nome atual, artista/título propostos, letra, fontes, revisão, nome final e resultado. |
| Detalhes | Atual/proposto por campo, candidatos, duração, versão, procedência, diferenças de letras e reprodução local de trecho. |
| Aplicação | Resumo das ações selecionadas, backups, espaço estimado, colisões e botão Aplicar. |
| Histórico | Operações por lote/arquivo, resultados, desfazer e exportar. |
| Recuperação | Operações interrompidas, caminhos encontrados, evidências e ações seguras disponíveis. |
| Configurações | Provedores, credenciais, dados enviados, modos, nomes, letras, perfil iPod, backups e concorrência. |

## Seleção e aprovação

Separar seleção de arquivos da aprovação de mudanças. Em cada item, permitir escolher correção de identificação, letra e nome independentemente. Um campo sem evidência suficiente permanece desmarcado. Alterar nome, candidato ou campo após aprovar invalida a aprovação anterior.

“Aplicar selecionados” mostra quantidade de arquivos e ações efetivas. Itens inválidos, sem backup viável ou com conflito ficam bloqueados com motivo visível; os demais podem prosseguir. Não apresentar uma confirmação genérica adicional para cada arquivo de um lote já aprovado.

Uma identificação confirmada sem letra mostra essa condição e permite aplicar título/nome. Letras existentes aparecem como preservadas por padrão; substituir abre comparação entre texto anterior e escolhido.

## Progresso e controle

Exibir etapa atual, concluídos/total, pendentes, conflitos e erros. Separar progresso de análise e de aplicação. Não apresentar tempo estimado até existir medição suficiente. Pausar muda para “Pausando” enquanto tarefas alcançam um ponto seguro.

Filtros: não analisados, revisão necessária, confirmação incompleta, reconhecidos sem letra, prontos para aplicar, aplicados e erros. Ordenação e seleção devem continuar utilizáveis durante processamento.

## Mensagens sugeridas

| Condição | Texto |
|---|---|
| Discordância | “As fontes encontraram versões diferentes. Revise antes de aplicar.” |
| Sem letra | “Música identificada. Nenhuma letra foi encontrada nas fontes consultadas.” |
| Indisponibilidade | “Esta fonte está indisponível. A confirmação ficou incompleta.” |
| Mudança externa | “O arquivo mudou desde a análise. Atualize a proposta antes de aplicar.” |
| Destino ocupado | “Já existe um arquivo com este nome. Revise o nome proposto.” |
| Arquivo bloqueado | “Outro programa está usando o arquivo. Tente novamente depois.” |
| Perfil não validado | “A compatibilidade com este dispositivo ainda não foi confirmada.” |

Detalhes técnicos ficam expansíveis e podem incluir um identificador de diagnóstico, sempre sem segredos.

## Acessibilidade e proteção de dados

Todos os controles principais precisam funcionar por teclado, com foco visível e nomes acessíveis. Estados usam texto e ícone, além de cor. Testar escalas de 100%, 150% e 200%, contraste, telas Retina e leitura de títulos longos. Validar atalhos e comportamento da janela no Linux e no macOS.

Ao configurar um reconhecedor por amostras, explicar o envio de trecho de áudio antes de habilitá-lo. Provedores pagos mostram orçamento do lote e consumo estimado/registrado, sem cadastrar contas ou ativar cobrança. Logs ficam locais; envio de diagnóstico não faz parte da primeira versão.

A prévia avisa que playlists conhecidas podem manter nomes antigos. Não prometer detecção de todas as referências externas. Reprodução é local e deve liberar o arquivo antes de uma tentativa de escrita.
