# Escrita, renomeação e recuperação

## Planejamento de nomes

Modelo padrão: `{artista} - {titulo}{versao}.{extensao}`. A versão inclui seu separador apenas quando preenchida. Modelo com faixa confirmada: `{faixa:02d} - {artista} - {titulo}{versao}.{extensao}`.

O modelo produz um basename, nunca um caminho. Rejeitar separadores, componentes `.`/`..` e qualquer expansão que escape da pasta. Resolver a pasta efetiva antes de planejar e imediatamente antes de executar; mudanças em links ou diretórios invalidam o plano.

Validar nomes conforme o sistema de arquivos de destino. Oferecer perfil portável que também trate caracteres proibidos pelo Windows, nomes reservados inclusive com extensão e pontos/espaços finais. Preservar acentos e Unicode, considerando normalização e sensibilidade a caixa efetivas do volume. Truncar a parte textual de forma determinística, conservando extensão e espaço para sufixo. Se não houver nome seguro, exigir revisão.

Reservar nomes para todo o lote, comparando com o disco. Colisões usam sufixos estáveis `(2)`, `(3)` ou revisão. Persistir o destino escolhido para que a retomada não escolha outro número. Uma alteração externa que ocupe o destino invalida a reserva; nunca autoriza sobrescrita.

Extensão incompatível com contêiner exige revisão explícita. Não trocar a extensão como forma de converter áudio. Mudanças apenas de caixa e ciclos de nomes exigem nomes intermediários únicos na mesma pasta.

## Tags e preservação

| Contêiner | Letra simples planejada |
|---|---|
| MP3 | ID3 USLT. |
| M4A | Atom ©lyr. |
| FLAC / Ogg Vorbis / Opus | Comentário LYRICS. |

Definir por formato os mapeamentos de artista, título, álbum, faixa, disco e ano antes de implementar o escritor. Preservar campos múltiplos e representações existentes quando não aprovados para mudança. Letras sincronizadas ficam separadas; não substituir letra simples por timestamps LRC.

Uma conversão de ID3 pode afetar frames desconhecidos. O perfil iPod antigo propõe ID3v2.3 e USLT UTF-16, mas só será declarado compatível após teste no aparelho indicado no roteiro. Se uma conversão implicar perda não aprovada, bloquear a aplicação desse perfil e mostrar o motivo.

## Protocolo por arquivo

1. Congelar plano aprovado, snapshot esperado e caminhos. Adquirir exclusividade lógica do item e reservas necessárias.
2. Revalidar diretório, identidade, tamanho, mtime e hash forte do arquivo antes de qualquer mutação. Mudança externa exige nova análise/revisão.
3. Verificar permissões, espaço de backup/temporário, disponibilidade dos destinos e condições do volume.
4. Registrar intenção de backup; copiar os bytes originais; verificar tamanho e hash; persistir backup criado.
5. Criar temporário exclusivo na pasta original, copiar o original e editar apenas campos aprovados.
6. Reabrir o temporário. Conferir tags selecionadas, campos preservados, capas e integridade do áudio. Persistir temporário validado.
7. Registrar intenção de preparar a origem; colocá-la sob nome intermediário exclusivo quando necessário. Persistir o caminho realmente encontrado.
8. Registrar intenção de finalizar; promover o temporário ao destino reservado com operação que não substitua arquivos alheios. Persistir destino finalizado.
9. Reabrir o destino, validar seu estado e atualizar caminho/snapshot no banco. Persistir concluída.
10. Remover intermediários próprios apenas depois da conclusão validada. Manter backup conforme retenção.

Para renomeação sem tags, usar o mesmo controle de identidade, backup e diário, dispensando edição de tags. Uma aplicação sem mudanças efetivas termina sem mutação e sem criar backup desnecessário.

O mecanismo concreto de promoção/substituição deve ser escolhido e testado por sistema operacional e volume, começando por Linux/ext4 e depois macOS/APFS. Incluir semântica de não sobrescrita, durabilidade, permissões, ACLs e atributos estendidos quando aplicáveis. Não presumir atomicidade do lote, da troca entre dois caminhos ou entre banco e disco. Se a origem ficar temporariamente sob outro nome, seu local precisa ser recuperável pelo diário.

Em ciclos, preparar os nomes intermediários de todos os participantes antes de ocupar destinos finais. Uma falha pode deixar apenas parte do grupo concluída: bloquear novas mutações nesse grupo até reconciliar todos os participantes. Não prometer atomicidade de grupo.

## Verificação de integridade

Hash do arquivo inteiro identifica backup e mudanças externas; ele muda com as tags. Para preservar áudio, usar comparação de frames/pacotes quando validada para o formato ou hash do PCM decodificado com parâmetros idênticos e ferramenta fixada. Registrar método, parâmetros e resultado. Falha de verificação impede o commit.

Preservar também capas e campos não selecionados por comparação semântica, além do áudio. Arquivos corrompidos ou que não podem ser validados ficam pendentes. Uma verificação incompleta não deve aparecer como integridade confirmada.

## Recuperação ao abrir

| Última fase persistida | Reconciliação necessária |
|---|---|
| Planejada | Confirmar se houve criação de backup antes da queda. Nenhuma mutação é presumida. |
| Backup criado | Verificar backup e origem; localizar eventual temporário ainda não registrado. |
| Temporário validado | Verificar origem, intermediários e destino antes de preparar novamente. |
| Origem preparada | Localizar o original intermediário e a cópia validada; concluir ou restaurar conforme evidências. |
| Destino finalizado | Verificar o destino e concluir o registro no banco sem reexecutar a escrita. |
| Concluída | Confirmar histórico; limpar apenas resíduos próprios identificados. |

Cada ação pode ter ocorrido antes da gravação de sua conclusão no banco. Por isso, reconciliar hashes e existência de todos os caminhos mesmo quando a última fase parecer anterior. Se houver ambiguidade, preservar os arquivos e solicitar resolução pela tela de recuperação.

## Desfazer e falhas

Desfazer é uma nova operação auditável. Verificar backup, estado atual do arquivo e disponibilidade do nome original. Restaurar bytes do backup por cópia temporária validada e restaurar o nome; só registrar reversão após conferir o resultado. Não consumir o único backup durante a restauração.

Se o arquivo foi alterado externamente ou o nome original está ocupado, bloquear restauração automática. Oferecer manter o atual ou restaurar uma cópia com nome alternativo, preservando ambas as versões. O segundo caso não conta como desfazer integral.

Falta de espaço impede iniciar a mutação. Arquivo bloqueado fica pendente. Perda do volume ou do local do backup exige reconciliar sua disponibilidade antes de continuar. Cancelamento durante commit aguarda um ponto recuperável. Nenhuma limpeza automática pode apagar a última cópia válida conhecida.
