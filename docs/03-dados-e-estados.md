# Modelo de dados e estados

## Persistência

SQLite local, com WAL e chaves estrangeiras habilitadas por conexão, implementado para a biblioteca. A entrega atual, o esquema efetivo e os procedimentos de recuperação estão em [Persistência da biblioteca](13-persistencia-da-biblioteca.md). As entidades abaixo também descrevem etapas futuras; jobs, planos e operações musicais ainda não estão implementados. A migração 3 acrescenta análises de letras e revisões aprovadas por campo, conforme [Credenciais, letras e aprovação](14-credenciais-letras-e-aprovacao.md). O banco residirá na área de dados do usuário retornada por platformdirs: convenções XDG no Linux e Library/Application Support no macOS. No Windows, usar a área local do usuário. O comando doctor informa os caminhos efetivos sem criar banco ou diretórios. Backups musicais terão local escolhido pelo usuário e não se confundem com cópias do banco.

UUIDs identificam entidades. Datas são armazenadas em UTC e exibidas no fuso local. Caminhos preservam Unicode e a grafia original; uma chave de comparação considera as regras do volume. Caminhos não são a identidade imutável de um arquivo.

## Entidades e relacionamentos

| Tabela | Dados principais e vínculos |
|---|---|
| files | UUID, caminho original/atual, diretório original, formato, tamanho, mtime, duração e assinatura atual. |
| file_snapshots | Arquivo, instante, tags, hash do arquivo e evidência de integridade do áudio. Snapshots são imutáveis. |
| runs | UUID, origens, opções congeladas, modo, início/fim e estado agregado. |
| run_files | Relação entre lote e arquivos; um arquivo pode aparecer em vários lotes. |
| jobs | Lote/arquivo, etapa, estado, tentativas, próxima tentativa, lease do worker e erro categorizado. |
| recording_candidates | Arquivo/consulta, provedor, ID externo, campos e evidências normalizadas. |
| lyric_candidates | Arquivo/consulta, origem, textos, versão, instrumental e procedência. |
| decisions | Arquivo, escolhas por campo, conflitos, aprovação e versão da política. |
| change_plans | Decisão, snapshot esperado, ações e destinos; versão e estado do plano. |
| operations | Plano, tipo aplicar/desfazer, estado atual e referências de recuperação. |
| operation_events | Operação, sequência, fase, instante, caminhos e evidências; diário incremental. |
| backups | Operação, caminho, tamanho, hash, data de verificação, retenção e disponibilidade. |
| provider_cache | Provedor, chave normalizada, versão do adaptador, resposta, expiração e tipo de resultado. |
| provider_events | Consulta, duração, categoria, tentativas e informações sanitizadas. |
| settings | Preferências sem segredos, versão e última alteração. |

Relacionamentos centrais: lote contém itens e jobs; arquivo possui snapshots e candidatos; decisão gera um plano; aprovação de uma versão do plano permite uma operação; operação possui eventos e backup.

## Restrições

Uma combinação de lote, arquivo e etapa identifica um job lógico. Uma versão aprovada de plano não pode gerar dois commits independentes. Alterar um campo ou destino invalida sua aprovação e gera nova versão. O executor aceita somente a versão aprovada e verifica novamente o snapshot.

Criar índices para jobs por estado/próxima tentativa, arquivos por caminho normalizado, operações incompletas, candidatos por arquivo e cache por provedor/chave/versão. A reserva de destinos deve impedir concorrência sobre o mesmo caminho. Participantes de um ciclo são registrados como grupo antes da execução.

Um fingerprint acústico permite reaproveitar candidatos, mas não prova identidade binária. Compartilhar resultado de reconhecimento não compartilha aprovação, backup ou operação entre arquivos.

## Estados independentes

| Eixo | Estados propostos |
|---|---|
| Lote | criado, inventariando, analisando, aguardando revisão, aplicando, pausando, pausado, cancelado, concluído, concluído com pendências. |
| Job | pendente, em execução, aguardando tentativa, concluído, sem resultado, falhou, cancelado. |
| Identificação | não analisada, confirmada, confirmação incompleta, conflito, não identificada. |
| Letra | não consultada, encontrada, preservada existente, conflito, instrumental confirmado, ausente, fonte indisponível. |
| Plano | rascunho, revisão necessária, aprovado, invalidado, em aplicação, aplicado, falhou. |
| Operação | planejada, backup criado, temporário validado, origem preparada, destino finalizado, concluída, requer recuperação, revertida. |

O estado agregado do lote é derivado dos itens; concluir com pendências não significa sucesso total. A interface mostra contagens por resultado.

## Retomada e consistência

Workers recebem leases temporários. Após encerramento inesperado, jobs cujo lease expirou são reconciliados; etapas apenas de leitura podem voltar à fila, enquanto operações de escrita consultam o diário antes de qualquer ação.

Não há transação única entre SQLite e sistema de arquivos. Persistir a intenção antes de cada mutação e registrar sua conclusão depois. Transações do banco devem ser curtas; não manter transação aberta durante HTTP, cópia de áudio ou interação do usuário.

Pausa impede novas tarefas. Cancelamento preserva resultados já obtidos e conduz mutações iniciadas a um estado recuperável. Retomar um lote usa suas opções congeladas; mudanças nas configurações globais não alteram silenciosamente um plano aprovado.

## Migrações, retenção e exportação

Cada migração tem versão e validação. Criar cópia consistente do banco antes de migrar, usando mecanismo compatível com SQLite/WAL. Uma base criada por versão mais nova não deve ser aberta para escrita por versão antiga.

Não excluir backups associados a operação incompleta ou recuperação pendente. Retenção de backups concluídos é configurável e sua limpeza exige ação explícita na primeira versão. Cache pode ser limpo sem apagar histórico, decisões ou backups.

Relatórios incluem UUID, caminho anterior/final, ações, estado, fontes, motivo e datas. Excluir credenciais, respostas brutas desnecessárias e texto completo das letras por padrão. Em CSV destinado a planilhas, neutralizar células que possam ser interpretadas como fórmulas.
