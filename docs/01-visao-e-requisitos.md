# Visão e requisitos

## Objetivo e público

Atender quem possui uma biblioteca local com nomes arbitrários, tags incompletas e letras ausentes. A interface será em português do Brasil. A identificação deve partir do áudio; nomes e tags existentes serão apenas pistas auxiliares.

## Escopo da primeira versão utilizável

Alvos atuais de desenvolvimento: macOS 15 Sequoia ou superior e Windows 11. Validar macOS separadamente em arm64 e x86_64. Linux, inicialmente Ubuntu 24.04 x86_64, continua como plataforma adicional. O núcleo não depende de APIs exclusivas de um desses sistemas. O escopo inclui seleção de múltiplas pastas; varredura opcionalmente recursiva; reconhecimento em múltiplos provedores; enriquecimento de metadados; consulta e comparação de letras; prévia por campo; escrita de tags; renomeação na mesma pasta; backup; recuperação; desfazer; pausa, retomada e relatório.

MP3, M4A com AAC/ALAC, FLAC, Ogg Vorbis e Opus são os formatos prioritários para leitura e escrita. O suporte só será declarado após validação por formato. WMA, APE, WAV e AIFF ficam para uma etapa posterior. AAC bruto e formatos sem escrita validada poderão ser inventariados com indicação da limitação.

Ficam fora do escopo: reorganizar diretórios, baixar músicas, transcrever vocais por IA, sincronizar dispositivos, editar áudio, converter formatos, distribuir um catálogo de letras e atualizar automaticamente playlists ou sidecars.

## Regras invariáveis

| ID | Regra |
|---|---|
| INV-01 | O diretório final de cada música é o diretório original, verificado no planejamento e na execução. |
| INV-02 | A análise não escreve nos arquivos musicais. Pode gravar cache e dados internos do aplicativo. |
| INV-03 | Nenhum arquivo alheio pode ser sobrescrito. |
| INV-04 | A escrita não transcodifica nem modifica o conteúdo do áudio. |
| INV-05 | Somente campos e ações aprovados podem ser aplicados. |
| INV-06 | Um backup completo e validado antecede qualquer mutação do original. |
| INV-07 | Identificação e letra têm decisões e níveis de confiança separados. |
| INV-08 | Nenhum commit interrompido pode ser repetido sem reconciliação do diário e dos arquivos. |

## Requisitos funcionais

| ID | Requisito | Evidência de aceitação |
|---|---|---|
| RF-01 | Adicionar e remover origens, selecionar recursividade e formatos. | Pastas sobrepostas não duplicam o mesmo caminho no lote. |
| RF-02 | Inventariar formato real, tags, duração e assinatura do arquivo. | Extensão incompatível é indicada; arquivo ilegível não interrompe o lote. |
| RF-03 | Reconhecer pelo áudio em provedores distintos. | Tags falsas não prevalecem sobre evidência incompatível do áudio. |
| RF-04 | Preservar candidatos e resolver divergências. | Versões ao vivo, remixes e covers conflitantes exigem revisão. |
| RF-05 | Consultar letras em duas fontes no modo completo. | Sucesso, ausência, instrumental e falha são resultados distintos. |
| RF-06 | Importar letra embutida, colada ou de arquivo TXT/LRC. | Origem local aparece na prévia e no histórico. |
| RF-07 | Mostrar alterações atuais e propostas por campo. | Usuário pode aceitar título e rejeitar álbum ou letra. |
| RF-08 | Gerar nomes válidos na mesma pasta conforme o sistema de arquivos. | Colisões do lote e do disco são detectadas antes da escrita; perfil de nomes portáveis é oferecido. |
| RF-09 | Aplicar seleção com backup e validação. | Apenas itens aprovados mudam; metadados não selecionados são preservados. |
| RF-10 | Pausar, retomar e cancelar tarefas. | Retomada não duplica consultas válidas nem commits concluídos. |
| RF-11 | Recuperar operações interrompidas e desfazer. | Nome e bytes originais são restaurados quando não há conflito externo. |
| RF-12 | Exportar relatório CSV/JSON. | Cada item informa resultado, fontes, alterações e motivo de falha. |
| RF-13 | Configurar fontes, credenciais, backups e perfil de compatibilidade. | Provedores pagos permanecem desativados por padrão. |

## Requisitos de qualidade

| ID | Requisito |
|---|---|
| RNF-01 | Rede, decodificação e escrita não executam na thread da interface. |
| RNF-02 | A distribuição futura deve executar diretamente em macOS 15+, Windows 11 e Linux, com pacote construído e validado por plataforma. Nesta etapa, a CLI exige Python instalado. |
| RNF-03 | Resultados já armazenados podem ser revisados e aplicados offline. Novas consultas exigem rede. |
| RNF-04 | Limites de acesso são compartilhados por provedor, independentemente do número de workers. |
| RNF-05 | Credenciais persistentes usam Keychain no macOS, WinVault no Windows 11 e Secret Service no Linux por adaptador. O ambiente é fallback quando ainda não há configuração salva. Logs e relatórios não expõem segredos. |
| RNF-06 | SQLite possui migrações versionadas, integridade referencial e recuperação documentada. |
| RNF-07 | Tabela de biblioteca utiliza modelo de dados que evite carregar widgets por arquivo. |
| RNF-08 | Toda decisão aplicada mantém procedência, versão das regras e aprovação. |

Metas numéricas de desempenho e de acerto serão definidas após medição de uma amostra conhecida. Até essa calibração, alta confiança é uma classificação explicável, sem promessa percentual.

## Políticas de decisão

No modo completo, consultar os dois reconhecedores habilitados e as duas fontes de letras, aproveitando cache válido. No modo rápido, a segunda fonte é acionada quando a primeira falhar ou deixar dúvida. MusicBrainz enriquece AcoustID e não conta como segundo reconhecedor independente.

Concordância entre reconhecedores sem conflito de versão permite propor alta confiança. Uma única fonte disponível implica confirmação incompleta. Discordância, candidatos próximos ou versão incerta exigem revisão. Nenhum resultado mantém a identificação pendente; falha de rede mantém a tarefa elegível para tentativa posterior.

Não inferir álbum, ano ou número de faixa apenas porque uma gravação aparece em um lançamento. A identificação de gravação não comprova a edição do arquivo.

Letras existentes são preservadas por padrão. A substituição exige opção explícita e prévia. Não combinar versos de fontes discordantes, inventar metadados ausentes ou tratar tradução como original. Uma faixa identificada pode ser renomeada e ter tags corrigidas mesmo sem letra.

Por autorização do usuário em 28/10/2026, a renomeação automática após novos reconhecimentos fica habilitada inicialmente quando pelo menos duas fontes independentes concordam e as verificações de integridade passam. A preferência é visível e pode ser desativada em Aplicar e restaurar. A autorização foi ampliada pelo usuário para artista/título quando as fontes concordam e para letras ausentes compatíveis quando a identidade e as tags atuais estiverem validadas. As três preferências podem ser desativadas separadamente e toda gravação exige backup. Outros campos e divergências exigem aprovação por campo. Abrir a biblioteca não aplica propostas antigas. Consulte [Automação, lotes e relatórios](17-automacao-lotes-e-relatorios.md).
