# Plano de implementação e validação

Este plano descreve a evolução do projeto. A base técnica dos itens 1 e 2 está implementada; E0 tem validação parcial registrada em [Validação inicial](09-validacao-inicial.md). Os itens 4 e 5 da lista de implementação estão entregues como inventário em memória e interface básica, conforme [Inventário e interface](10-inventario-e-interface.md). A persistência SQLite do antigo item 3 está implementada, conforme [Persistência da biblioteca](13-persistencia-da-biblioteca.md); E1 ainda requer homologação prática nos sistemas alvo. E4/E5 têm implementação inicial descrita em [Aplicação e restauração](16-planejamento-aplicacao-e-restauracao.md), ainda sujeita à homologação Windows e testes ampliados por volume/formato. A orientação atual prioriza compatibilidade com macOS 15 Sequoia+ e Windows 11, mantendo Linux como plataforma adicional. A ordem Linux/macOS registrada nas entregas abaixo é histórica e não dispensa validação em Windows 11.

## Entregas e dependências

### Situação atualizada em 29/10/2026

O usuário informou que já realizou testes com músicas reais da própria biblioteca, incluindo faixas presentes em suas playlists do Spotify, usadas como referência de identificação. Com essa confirmação, os itens **2 (homologação do fluxo com músicas reais)** e **4 (validação das identificações e da automação na amostra conhecida)** da lista de pendências apresentada na conversa são considerados atendidos no escopo testado pelo usuário. Esses números se referem à lista de pendências, e não às etapas E2/E4 abaixo. Não foram fornecidas métricas quantitativas, tamanho da amostra ou uma relação dos formatos e cenários exercitados; não se atribuem números a essa validação.

A suíte automatizada também foi executada nativamente em Windows 11, conforme o [registro de validação](18-teste-no-windows-11.md). As referências históricas deste plano à ausência de piloto e de testes nativos Windows devem ser lidas com essas atualizações. Permanecem separados os testes de instalador, arquiteturas, volumes, escala e aparelhos específicos, além da distribuição e demais funcionalidades pendentes.

Foi acrescentada a geração do [instalador Windows autossuficiente](19-instalador-windows.md), com runtime Python, Qt e auxiliares de áudio incluídos, atalhos e desinstalador. Trata-se de um pacote inicial para validação privada; distribuição pública, assinatura e homologação em máquina limpa permanecem separadas.

| Etapa | Entrega futura | Condição de saída |
|---|---|---|
| E0 | Prova de provedores e licenças. | Confirmar integrações reais, credenciais, versões, envio de dados, limites e viabilidade do segundo reconhecedor. |
| E1 | Inventário, SQLite e interface básica. | Pastas sobrepostas, formatos reais, arquivos inválidos e interface responsiva tratados sem alterar músicas. |
| E2 | Reconhecimento, cache e resolução. | Identificar amostra com tags falsas; preservar conflitos e justificar decisões. |
| E3 | Letras e revisão por campo. | Consultar ambas as fontes no modo completo e distinguir todos os resultados. |
| E4 | Planos, nomes e reservas. | Nenhum destino sai da pasta original; colisões e ciclos aparecem antes da escrita. |
| E5 | Tags, backup, diário, recuperação e desfazer. | Testes por formato e interrupção passam sem perda de áudio nem sobrescrita alheia. |
| E6 | Lotes, limites, pausa e relatórios. | Retomada não duplica commits; cotas são compartilhadas; falha de um item não derruba os demais. |
| E7 | Pacote Linux e documentação de uso, seguido por pacote macOS. | Executar em instalações limpas de cada plataforma; incluir dependências, avisos e instruções de recuperação. |
| E8 | Piloto e compatibilidade do iPod. | Revisar métricas da biblioteca real e validar o aparelho antes de anunciar suporte. |

E1 pode ser preparada enquanto E0 é investigada, mas o requisito de dois reconhecedores continua pendente até sua demonstração. E4 depende das decisões de E2/E3. E5 exige plano estável e é obrigatória antes de liberar qualquer escrita ao usuário. A primeira versão utilizável reúne E1 a E7 com as integrações validadas de E0.

Atualização dos itens 6 a 8: E2 tem adaptadores integrados à janela, cache, comparação de candidatos e enriquecimento MusicBrainz, com evidência real registrada em [Reconhecimento e resolução](11-reconhecimento-e-resolucao.md). Isso não encerra a calibração de confiança nem a homologação nas plataformas alvo. Inventário, candidatos e propostas agora têm persistência SQLite; a fila persistente com pausa e retomada está implementada no escopo inicial de E6, conforme [Automação, lotes e relatórios](17-automacao-lotes-e-relatorios.md). E3 tem letras públicas na interface, importação local, comparação e aprovação por campo implementadas, conforme [Credenciais, letras e aprovação](14-credenciais-letras-e-aprovacao.md). As consultas de letras do probe continuam disponíveis. A aplicação com backup e restauração está implementada em E4/E5. E6 inclui relatórios CSV/JSON, checkpoints e orçamento AudD persistente; a homologação nativa Windows, distribuição e piloto permanecem pendentes.

## Matriz de validação

| Caso | Cenário | Resultado exigido | Rastreabilidade |
|---|---|---|---|
| TA-01 | MP3 com tags falsas e nome arbitrário. | Proposta parte do áudio, com origem e evidências. | RF-03 |
| TA-02 | Versão de estúdio versus ao vivo/remix/cover. | Conflito exige revisão; álbum não é inferido sem suporte. | RF-04 |
| TA-03 | Letra ausente, instrumental e HTTP indisponível. | Estados distintos, sem misturar resultados. | RF-05 |
| TA-04 | Letra anterior e fontes discordantes. | Preservação padrão; substituição seletiva com diferenças. | RF-06/07 |
| TA-05 | MP3, M4A AAC/ALAC, FLAC, Vorbis e Opus. | Escrever/reler tags e letra, preservar capa e conteúdo de áudio. | INV-04/05 |
| TA-06 | Unicode composto/decomposto, caixa, caracteres proibidos e caminho longo em ext4/APFS. | Nome válido, determinístico e na pasta original; perfil portável validado separadamente. | INV-01; RF-08 |
| TA-07 | Destino preexistente, colisão entre propostas, troca de caixa e ciclos. | Nenhuma sobrescrita; grupo recuperável após falha. | INV-03/08 |
| TA-08 | Arquivo muda entre análise e aplicação. | Plano invalidado sem mutação. | RF-09 |
| TA-09 | Falta de espaço, permissão ou arquivo bloqueado. | Item pendente/falhou com causa; demais continuam. | RF-09/10 |
| TA-10 | Queda antes/depois de cada mutação e registro no diário. | Reabertura localiza cópias válidas e não duplica commit. | INV-06/08 |
| TA-11 | Desfazer normal e com conflito externo. | Restauração exata no primeiro; preservação das versões no segundo. | RF-11 |
| TA-12 | Pausa, fechamento, retomada e cache válido. | Retoma tarefas necessárias sem reaplicar operações. | RF-10 |
| TA-13 | Muitos workers recebem 429/Retry-After. | Pausa compartilhada e limites globais respeitados. | RNF-04 |
| TA-14 | Credencial inválida e relatório exportado. | Suspende fonte; nenhum segredo no banco de eventos/exportação. | RNF-05 |
| TA-15 | Biblioteca grande e escalas de tela diferentes. | Navegação, seleção, foco e cancelamento utilizáveis. | RNF-01/07 |
| TA-16 | Pacotes em Linux/macOS limpos e teste no iPod indicado. | Dependências de execução incluídas conforme formato de distribuição; compatibilidade do aparelho medida separadamente. | RNF-02; E8 |

## Estratégia de testes

Testes determinísticos cobrem normalização, versões, confiança, nomes, reservas, estados e contratos. Fixtures locais cobrem formatos, capas e metadados desconhecidos. Testes de integração por plataforma cobrem locks, caixa, Unicode, permissões, atributos, caminhos, promoção de temporários e recuperação. A CI inicial testa o núcleo sem rede; integração real dos provedores é executada separadamente.

Injetar falhas antes e depois de cada etapa de sistema de arquivos e persistência. Incluir falha durante o próprio desfazer e indisponibilidade do volume de backup. Conferir bytes originais após restauração e ausência de exclusão de arquivos não pertencentes à operação.

Testes online ficam separados, pequenos e optativos, com arquivos autorizados e credenciais próprias. Não fazem parte de toda execução de testes e não substituem testes locais. Respostas de teste armazenadas devem respeitar retenção e termos do serviço.

## Piloto e métricas

Montar amostra conhecida com idiomas, gêneros, versões, faixas cortadas, instrumentais, nomes incorretos e formatos prioritários. Registrar verdade de referência manual por gravação, sem confundir gravação com edição de álbum.

Medir acerto de identificação, falso positivo, conflitos, cobertura por fonte, correção da letra, quantidade de revisões, latência por etapa, uso de disco/memória e sucesso de restauração. Informar tamanho e composição da amostra junto aos resultados. A calibração deve favorecer revisão quando houver ambiguidade; limiares de automação permanecem pendentes até essa avaliação.

## Pronto para distribuição

Requisitos obrigatórios rastreados; testes aplicáveis aprovados; recuperação demonstrada; dependências fixadas; pacote em máquina limpa; licenças e fontes correspondentes tratadas; nenhuma credencial embutida; instruções de instalação, backup, limites e recuperação revisadas. Publicação, assinatura e instalador são decisões posteriores ao pacote portável validado.

## Riscos e decisões pendentes

| Risco/decisão | Tratamento e momento |
|---|---|
| ShazamIO deixar de funcionar. | E0 valida; substituir conector ou configurar provedor oficial. Não contar MusicBrainz como segundo reconhecedor. |
| Termos, cotas ou custos mudarem. | Revalidar fontes oficiais em E0 e a cada distribuição. |
| Biblioteca sofrer alteração externa. | Snapshot/hash antes da escrita e bloqueio de plano desatualizado. |
| Falha de disco ou backup inacessível. | Verificação prévia, hashes, diário e bloqueio de mutação sem cópia válida. |
| Perfil iPod não preservar frames. | Fixtures e aparelho real; não anunciar compatibilidade antes da evidência. |
| Retenção de backup consumir disco. | Estimativa prévia e limpeza explícita; preservar operações pendentes. |
| Limiares e metas de desempenho desconhecidos. | Definir após piloto, sem porcentagens ou prazos inventados. |
| Nome Afinário e licença final. | Validar antes da identidade pública e da distribuição. |

Não há estimativa de calendário nesta documentação: ela depende da prova das integrações, do tamanho da equipe e da disponibilidade de arquivos/dispositivos de teste.

Atualização de aplicação: E4/E5 incluem prévia, nomes portáveis, renomeação por concordância, escritores por campo nos formatos prioritários, backups verificados, diário, recuperação e restauração. Ciclos de nomes manuais são detectados e bloqueados; execução de ciclos e homologação de volumes continuam pendentes. E6 inclui pausa/retomada persistente e relatórios CSV/JSON, conforme a entrega 17. Empacotamento e homologação nativa Windows continuam pendentes; o [guia Windows 11](18-teste-no-windows-11.md) orienta o teste pelo código-fonte.
