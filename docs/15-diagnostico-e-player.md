# Diagnóstico do reconhecimento e player

Atualização de 28/10/2026, desenvolvida e validada em macOS. Windows 11 continua como alvo, com validação nativa desta entrega pendente.

## Consultas concluídas e resultado da identificação

Encerrar o lote significa que suas tentativas terminaram. A música pode ter fontes concordantes, precisar de revisão, não ter correspondência ou estar com a consulta bloqueada/com falha. A tabela e o resumo final distinguem esses resultados; sinais atrasados de progresso não podem substituir o resultado final. Arquivos não iniciados ao cancelar e falhas de persistência também recebem um estado final na sessão.

A coluna Fontes e seus tooltips distinguem credencial ausente, executável ausente, limite da execução AudD, recusa de acesso, limite do provedor e falha de rede. Os detalhes incluem a mensagem de cada fonte e suas tentativas. Os rótulos corrigidos também se aplicam aos relatórios antigos da biblioteca; eles continuam representando a situação da consulta original até uma nova identificação.

## Credencial presente não significa acesso validado

Os tokens continuam no cofre nativo. A interface mostra quando uma credencial está presente e lista executáveis ausentes. AcoustID precisa de `fpcalc`; FFmpeg prepara amostras para AudD e ShazamIO. O aplicativo não instala ferramentas automaticamente. Neste Mac, `chromaprint` foi instalado durante a correção para disponibilizar `fpcalc`.

A [documentação AcoustID](https://acoustid.org/webservice#api-keys) diferencia a chave de aplicação (`client`, usada na identificação) da chave de usuário (usada em submissões). Respostas de erro JSON com HTTP 400 são interpretadas para mostrar recusa da chave, inclusive o código 4. O transporte suspende novas requisições dessa fonte no mesmo lote após uma recusa de autenticação; não registra o token ou a resposta bruta.

AudD requer token, serviço selecionado e limite acima de zero para novas consultas. O limite pode ser configurado tanto na lateral quanto em Serviços e ferramentas, e fica salvo. Zero bloqueia envios mesmo com token presente. Nenhum limite é aumentado automaticamente. Respostas válidas em cache podem ser reutilizadas sem novas consultas.

As opções dos reconhecedores selecionados passam a ser restauradas ao reabrir. A opção de ignorar cache não é restaurada, evitando novas consultas involuntárias após reiniciar.

## Nomes diferentes em consultas posteriores

As respostas externas podem mudar. A escolha de representantes duplicados do mesmo MBID é determinística, mesmo se o provedor alterar a ordem dos candidatos. Após comparar as fontes atuais, o worker compara a proposta com o histórico do mesmo hash e snapshot do arquivo. Diferenças de artista, título ou gravação exigem revisão; variações apenas de caixa, pontuação ou acentuação latina são normalizadas.

A proposta anterior fica disponível na lista de candidatos em Revisar e aprovar, com origem Identificação anterior. Ela não conta como uma fonte independente na votação. Nenhuma mudança é aplicada às tags ou ao nome do arquivo; a escolha manual continua disponível e as aprovações anteriores precisam ser revistas quando as evidências mudam.

## Ouvir antes de aprovar

O player fica abaixo dos detalhes da biblioteca. Selecionar uma linha prepara o arquivo, sem tocar automaticamente. Reproduzir ou dois cliques na linha inicia o áudio; o mesmo botão pausa e retoma. Parar reinicia a posição. A barra permite buscar um ponto, e o controle de volume afeta somente o player. Selecionar outra faixa ou fechar a janela interrompe a reprodução e libera a fonte.

O extra `gui` agora inclui `PySide6-Addons`, que fornece Qt Multimedia, além de Essentials. A implementação usa [QMediaPlayer](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QMediaPlayer.html) e [QAudioOutput](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QAudioOutput.html), sem comandos exclusivos de macOS ou Windows. Os formatos reproduzíveis dependem do backend e dos codecs disponíveis em cada sistema. Arquivos ausentes, links e erros de reprodução são tratados na interface. O player lê o arquivo local e não envia áudio aos provedores.

## Evidências desta entrega

- 258 testes aprovados, incluindo credenciais persistidas exercitando ambos os provedores por HTTP simulado, orçamento AudD, autenticação AcoustID com HTTP 400, isolamento de falhas entre fontes, propostas divergentes persistidas após reiniciar e rejeição de sinais de etapa posteriores ao resultado final.
- Reprodução e decodificação reais de MP3 em teste, com saída silenciada: pausa, busca de posição, volume, parada, liberação da fonte e bytes originais preservados.
- Janela nativa macOS aberta com inventário sintético e player funcionando. Captura local em `reports/afinario-player.png`, ignorada pelo Git.
- Ruff e formatação aprovados; dependências instaladas a partir do lock atualizado.
- Diagnóstico da biblioteca real confirmou `fpcalc` ausente, AudD sem tentativas por limite da execução e limitação temporária do ShazamIO. Após instalar `fpcalc`, uma consulta real ao AcoustID retornou recusa da chave (código 4); nenhuma credencial foi exibida. AudD foi testado com transporte simulado, sem consumir consultas pagas reais.

As credenciais recusadas precisam ser substituídas pelo usuário por uma chave válida. Esta entrega não cria contas, não obtém chaves em nome do usuário e não altera seu orçamento AudD.
