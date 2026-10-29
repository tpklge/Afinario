# Automação, lotes e relatórios

Entrega de 28/10/2026, validada localmente no macOS. Mantém macOS e Windows 11 como alvos; a homologação nativa em Windows continua pendente.

## Automação

Em **Aplicar e restaurar**, três preferências independentes começam habilitadas e são persistidas: renomeação por concordância, preenchimento de artista/título por concordância e busca/aplicação de letras compatíveis.

Artista e título só são gravados automaticamente quando pelo menos dois reconhecedores de áudio independentes concordam e passam pelas regras de duração, versão e identidade. AcoustID, AudD e ShazamIO podem votar; MusicBrainz e fontes de letras não acrescentam votos. Divergências históricas ou edições manuais incompatíveis impedem a automação. Álbum, ano e faixa continuam dependendo de revisão, pois a concordância de identidade não determina a edição do lançamento.

Após a aplicação de artista/título, a busca de letras usa as tags atuais. A aplicação automática exige identidade corroborada, artista/título atuais correspondentes, ausência de letra embutida e candidato com artista, título e duração compatíveis. Textos discordantes, resultados incompletos, instrumental e edições manuais de letra permanecem para revisão. Uma fonte pode fornecer o texto quando não há conflito e os dados necessários foram verificados. Letras existentes são preservadas; substituí-las continua exigindo autorização explícita e aprovação manual.

Toda escrita usa o fluxo de backup, cópia temporária, releitura e verificação de áudio já descrito em [Aplicação e restauração](16-planejamento-aplicacao-e-restauracao.md). A operação registra os campos automáticos sem inventar uma aprovação manual. As evidências são reavaliadas antes da escrita. Ausência de FFmpeg bloqueia a escrita de tags. Abrir a biblioteca não aplica propostas antigas.

As caixas de aprovação têm indicador de 24 pixels, altura mínima de 42 pixels, contraste e foco visíveis. Toda a área do controle responde ao clique, inclusive fora do pequeno quadrado; a tecla Espaço continua funcionando.

## Pausa e retomada

**Pausar lote** está disponível durante varredura, identificação, letras e aplicação. A pausa aguarda consultas em andamento ou a operação do arquivo atual terminarem em segurança. Enquanto isso, o aplicativo informa que está pausando. O cancelamento permanece uma ação separada.

Em **Lotes e relatórios**, selecione o lote pausado ou interrompido e use **Retomar lote selecionado**. O estado persiste após fechar e reabrir a janela. Ao fechar durante uma tarefa compatível, o aplicativo solicita pausa e aguarda o ponto seguro antes de encerrar. Abrir a janela não retoma chamadas ou alterações automaticamente.

O esquema SQLite 5 acrescenta `task_batches` e `task_items`, com opções originais, ordem e checkpoints por música. Resultados e conclusão do item são confirmados na mesma transação. Itens concluídos não são reaplicados; operações interrompidas passam primeiro pela recuperação existente. Um lock por lote impede execução concorrente do mesmo trabalho. A varredura percorre novamente os diretórios, reutilizando a leitura de metadados dos arquivos concluídos que permanecem inalterados.

O orçamento AudD mantém o limite original e registra cada reserva antes do envio. Retomar não zera a contagem nem aumenta o limite ao mudar as configurações globais. Respostas válidas em cache podem ser reutilizadas. Uma queda durante a entrega HTTP pode deixar incerto se o provedor recebeu a requisição; a retomada pode precisar consultar novamente, respeitando as reservas restantes. Não há promessa de execução exatamente uma vez em servidores externos.

A tabela distingue estado do lote, itens processados, falhas e uso AudD. A pausa de uma etapa impede iniciar a próxima fase automática até a retomada explícita. Arquivos alterados externamente continuam sujeitos às verificações de snapshot e integridade.

## Relatórios

Na mesma aba, exporte a biblioteca ou as músicas selecionadas em JSON ou CSV. A exportação acontece em segundo plano e recusa sobrescrever um arquivo existente. CSV usa UTF-8 com BOM para facilitar a abertura em planilhas e neutraliza prefixos de fórmulas em células.

Os relatórios incluem caminhos, tags atuais, fontes e motivos da identificação, situação das letras, campos propostos/aprovados, operações, campos automáticos, evidências históricas das novas operações, caminhos de backup e estados/checkpoints dos lotes. JSON mantém as estruturas detalhadas; CSV separa linhas de música, operação e lote. Relatórios selecionados filtram arquivos e itens associados.

Credenciais, fingerprints, áudio, respostas HTTP brutas, opções internas dos lotes e textos completos de letras não são exportados. Para letras alteradas, o relatório informa presença e quantidade de caracteres. Caminhos e metadados fazem parte do relatório escolhido pelo usuário. Arquivos exportados dentro de `reports/` são ignorados pelo Git.

## Validação

Resultado local: **317 testes aprovados**, Ruff e formatação sem erros. A cobertura inclui tags por concordância, bloqueios de letras incompatíveis, gravação/restauração de letras, pausa/retomada dos quatro tipos de lote, fechamento/reabertura da interface, checkpoints de aplicação após interrupção, limite AudD persistente e exportação sem segredos/textos de letras.

Três testes adicionais na plataforma Cocoa nativa do macOS validaram clique fora do indicador, pausa/retomada após reabrir e o fluxo completo identificação → tags → busca de letras → gravação com dois backups. Usaram áudio sintético, serviços simulados e dados locais isolados; não consumiram APIs nem modificaram músicas da biblioteca real. Capturas em `reports/afinario-automation-native.png`, `reports/afinario-approvals-native.png` e `reports/afinario-batches-native.png`, ignoradas pelo Git.
