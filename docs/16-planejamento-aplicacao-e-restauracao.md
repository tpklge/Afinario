# Planejamento, aplicação e restauração

Entrega de 28/10/2026. Implementada e validada localmente em macOS; a homologação nativa em Windows 11 permanece pendente. Inclui planejamento de nomes, aplicação por campo, backups, histórico, recuperação e restauração.

## Como usar

1. Abra **Aplicar e restaurar**. Escolha uma pasta de backups ou mantenha o padrão: `backups` junto ao banco local da biblioteca, fora do projeto.
2. **Renomear após identificar quando 2 ou mais fontes concordarem** fica habilitado inicialmente, conforme a autorização desta entrega. A preferência é persistida. Desmarcar desativa o disparo automático após novos reconhecimentos.
3. Artista/título com concordância e letras ausentes compatíveis agora também têm automação opcional, conforme [Automação, lotes e relatórios](17-automacao-lotes-e-relatorios.md). Para os demais campos ou decisões manuais, salve sua aprovação em **Revisar e aprovar**. Depois use **Prévia das selecionadas** ou **Prévia da biblioteca**. A prévia inclui os campos aprovados e os nomes com concordância suficiente.
4. Confira origem, destino, campos e situações. **Aplicar itens prontos com backup** executa somente os itens prontos do plano salvo. Mudanças posteriores no arquivo, na aprovação ou nas evidências invalidam o item.
5. Em **Backups e restauração**, selecione uma operação concluída e use **Restaurar operação selecionada** para restaurar nome e bytes anteriores. A restauração também cria backup da versão atual.

Abrir o aplicativo não aplica automaticamente as propostas antigas. A execução automática é disparada após novos reconhecimentos e, para letras compatíveis ausentes, após a consulta de letras. A restauração da biblioteca na abertura não dispara aplicação. Cancelar um lote de identificação não inicia renomeações automáticas.

## Critério de concordância

Somente AcoustID, ShazamIO e AudD contam como reconhecedores independentes. O resolvedor precisa retornar concordância para pelo menos dois reconhecedores distintos, incluindo as verificações existentes de duração, versão, artista/título e identificadores. MusicBrainz, letras, candidatos históricos e repetições do mesmo provedor não acrescentam votos.

A política reavalia as evidências armazenadas; o rótulo de concordância isolado não autoriza mutações. Divergência entre buscas impede a renomeação automática. Edições manuais de artista/título que divergem da decisão e nomes editados ainda não aprovados também impedem o disparo automático.

A autorização automática cobre o nome, no modelo `Artista - Título.extensão`, e foi ampliada para artista/título e letras ausentes compatíveis em [Automação, lotes e relatórios](17-automacao-lotes-e-relatorios.md). O usuário pode aprovar um nome manual mesmo sem concordância, usando o fluxo de prévia e aplicação.

## Nomes e colisões

Os arquivos permanecem na pasta efetiva original, com extensão preservada. Nomes gerados preservam Unicode e acentos, substituem caracteres proibidos e são limitados em UTF-8 e UTF-16. Comparações de colisão consideram caixa e equivalência Unicode de modo conservador para portabilidade entre macOS e Windows.

Colisões de nomes gerados recebem sufixos determinísticos `(2)`, `(3)` etc., reservados na prévia. Nomes manuais aprovados que já estão ocupados ficam bloqueados. Trocas cíclicas entre nomes de dois arquivos também ficam bloqueadas nesta entrega; não são executadas silenciosamente. Mudanças somente de caixa usam um intermediário exclusivo.

O destino é verificado novamente antes de aplicar, e a promoção usa criação/renomeação sem substituição de um arquivo preexistente. Uma ocupação posterior ao planejamento bloqueia o item. A semântica nativa usa `renamex_np(RENAME_EXCL)` no macOS e `MoveFileExW(WRITE_THROUGH)` sem `REPLACE_EXISTING` no Windows, que recusa destino existente. O fallback Linux usa criação exclusiva de vínculo seguida de remoção da origem; uma interrupção dentro desse fallback pode exigir verificação manual dos vínculos.

## Gravação e integridade

Há escrita validada inicialmente para MP3, M4A AAC/ALAC, FLAC, Ogg Vorbis e Opus. Os demais formatos continuam inventariáveis; renomeação sem tags pode ser planejada com evidência suficiente, mas escrita de tags fica bloqueada.

Mapeamentos de letras: MP3 usa USLT e SYLT com milissegundos; M4A usa ©lyr e o campo separado `----:com.apple.iTunes:SYNCEDLYRICS`; FLAC/Vorbis/Opus usam LYRICS e SYNCEDLYRICS. O campo livre de letra sincronizada M4A depende do suporte de cada player; compatibilidade com iPod não é declarada. Letra simples e sincronizada são aprovadas e gravadas separadamente.

Antes da mutação, o serviço confere snapshot, revisão, evidências, hash SHA-256, identidade do arquivo e identidade da pasta. Links, junctions, arquivos especiais e múltiplos vínculos físicos são bloqueados. Espaço para backup e cópia de trabalho é estimado antes da escrita.

O serviço cria uma cópia integral exclusiva para backup, confirma seu hash e registra a fase no SQLite. As tags são editadas em uma segunda cópia na pasta da música. A cópia é reaberta para conferir campos escolhidos, tags não aprovadas, capas e estruturas adicionais preservadas pelo leitor. MP3 mantém ID3v2.3 ou v2.4 sem conversão implícita e preserva bytes ID3v1 existentes. Frames desconhecidos ID3 e blocos adicionais FLAC também são comparados.

Para escrita de tags, o FFmpeg decodifica todas as faixas de áudio de origem e cópia em PCM de 32 bits; hashes por stream precisam coincidir. O arquivo instalado mantém seu áudio codificado original: a decodificação é somente uma verificação. Ausência de FFmpeg, falha de releitura ou divergência impede substituir o original.

Renomeação sem tags exige igualdade do hash integral entre original, backup e cópia. A cópia nativa preserva atributos, ACLs e atributos estendidos pelo `copyfile` no macOS e `CopyFileW` no Windows 11. As garantias efetivas ainda precisam de homologação nos volumes e permissões Windows usados pelo usuário.

## Diário, recuperação e desfazer

O esquema 4 acrescenta planos imutáveis, operações, eventos de fase, reservas de arquivos ativos e evidências vinculadas aos novos snapshots. O backup automático do banco precede a migração.

Depois da cópia validada, a origem passa a um intermediário exclusivo. A promoção ao destino não substitui arquivos alheios. A atualização do caminho/snapshot e a conclusão da operação são confirmadas na mesma transação SQLite, preservando o UUID. Aprovações anteriores são invalidadas; evidências de reconhecimento são mantidas para o mesmo áudio verificado.

Um lock do sistema impede duas instâncias de aplicar/recuperar ao mesmo tempo. Arquivos com operação ativa recusam novas aprovações e reconhecimentos. Uma nova varredura é bloqueada enquanto houver mutações ou recuperações pendentes, evitando inventariar um estado intermediário. Cópias internas com prefixo `.afinario-` não entram na varredura e são ignoradas pelo Git.

Na abertura, o worker reconcilia operações interrompidas. Se o SQLite ainda não confirmou a conclusão, a recuperação busca preservar/restaurar o original, reconhecendo os arquivos por identidade e hash. Se já confirmou, não reaplica a escrita e apenas tenta limpar intermediários próprios. Não há promessa de atomicidade do lote: itens anteriores podem estar concluídos quando outro falha.

Se o nome original foi ocupado ou um arquivo intermediário foi alterado externamente, a recuperação mantém as versões e o backup, registra **Recuperação pendente** e bloqueia novas mutações do item. Após resolver o conflito, **Verificar recuperação** tenta novamente. Não há sobrescrita forçada nem limpeza automática de backups.

Restaurar exige que a versão atual corresponda ao hash de saída registrado e que o nome original esteja disponível. Backups alterados ou ausentes bloqueiam a restauração. Alterações mais recentes da mesma música precisam ser restauradas antes das anteriores. O único backup nunca é consumido na restauração.

## Validação

Testes locais incluem nomes portáveis, Unicode, colisões, mudança de caixa, ciclos bloqueados, reexecução do mesmo plano, aprovações desatualizadas, arquivo modificado, destino ocupado durante commit, falta de cópia, cancelamento, backup corrompido, verificação de áudio com falha, escrita e restauração nos formatos prioritários, M4A ALAC, ID3v2.3/ID3v1 e letras simples/sincronizadas separadas.

As interrupções são injetadas antes/depois das fases de mutação e da confirmação no banco. Também há subprocessos encerrados com `os._exit`, seguidos por reabertura e recuperação. Testes de interface percorrem prévia, aplicação e restauração, e a renomeação automática usa provedores simulados sem consumir APIs reais.

A CI desktop instala FFmpeg quando necessário para executar as verificações de escrita em Linux, macOS e Windows. Sua execução remota e a homologação em equipamentos Windows 11 não foram realizadas nesta sessão.

Referências: [MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw), [FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers), [Mutagen ID3](https://mutagen.readthedocs.io/en/latest/user/id3.html), [os.rename](https://docs.python.org/3/library/os.html#os.rename), [CopyFileW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-copyfilew) e cabeçalho `copyfile.h` do SDK macOS instalado.

Resultado local: **298 testes aprovados**, Ruff e formatação sem erros. Uma prova adicional na janela nativa macOS percorreu prévia, escrita de título aprovado, renomeação, backup e restauração byte a byte em áudio sintético; capturas locais em `reports/afinario-application-preview.png` e `reports/afinario-backups.png`, ignoradas pelo Git. Nenhuma alteração musical foi aplicada à biblioteca real nesta validação.
