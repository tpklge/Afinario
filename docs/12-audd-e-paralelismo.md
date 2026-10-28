# AudD e paralelismo

Atualização de 28/10/2026. O usuário informou que contratou o plano básico AudD e solicitou sua integração. Nenhuma assinatura foi criada ou alterada pelo aplicativo.

## Configurar e testar

Reabra a janela atualizada:

```powershell
.\.venv\Scripts\python.exe -m afinario gui
```

1. Em Reconhecer → Serviços e ferramentas…, informe o Token AudD no campo mascarado e confirme Usar nesta sessão. Ele não será gravado pelo diálogo.
2. Marque Usar AudD (plano pago). Para usar duas fontes independentes sem ShazamIO, mantenha AcoustID e AudD habilitados e desmarque ShazamIO.
3. Defina Limite AudD nesta execução. Comece com 1 e selecione uma música para validar o token. O padrão 0 bloqueia novas consultas, mas permite aproveitar cache válido.
4. Clique em Identificar selecionadas ou Identificar biblioteca. A janela informa tentativas reservadas/limite e mostra resultados AudD nos detalhes e nas fontes.

Alternativamente, configure `AFINARIO_AUDD_TOKEN` no ambiente antes de abrir a aplicação. No Windows, o leitor também aceita a variável persistente do usuário. Não coloque o token no TOML, no código ou no chat. O extra recognition só é necessário para ShazamIO; AudD usa HTTPX já instalado e FFmpeg para extrair o trecho. ffprobe é necessário quando não há duração local disponível.

## Contrato AudD

O adaptador envia uma amostra WAV de até 12 segundos, em multipart POST para `https://api.audd.io/`, com api_token no corpo e nome genérico sample.wav. O arquivo original, seu caminho e sua duração completa não são enviados. Não é usado o endpoint enterprise, nem é enviado o arquivo inteiro.

Há uma amostra por arquivo, sem segunda tentativa automática de áudio. A chamada HTTP paga tem exatamente uma tentativa: timeout, resposta inválida ou falha do servidor não disparam reenvio automático. O próximo clique em Identificar é uma nova execução, sujeita a novo limite e a aproveitamento do cache.

Artista e título são normalizados para o contrato comum. song_link e ISRC são preservados quando fornecidos; identificadores ausentes ficam ausentes. timecode representa uma posição e não é convertido em duração da faixa. Álbum/data retornados são alternativas para revisão e não se tornam tags aprovadas. Recursos enterprise ausentes não são inventados.

AudD é um reconhecedor independente. MusicBrainz continua sendo enriquecimento. Com três fontes habilitadas, uma discordância de qualquer fonte exige revisão; concordância de duas não encobre uma terceira divergente.

Contrato e condições foram conferidos na [documentação oficial AudD](https://docs.audd.io/) e na [página de preços](https://audd.io/pricing/index.html). O plano básico usa assinatura com franquia e excedentes; o aplicativo não consulta saldo nem prevê a fatura da conta.

## Orçamento local

O limite é por execução do botão Identificar, compartilhado por todas as músicas e threads. Uma reserva atômica ocorre imediatamente antes de iniciar o envio HTTP, depois de obter o slot do provedor. Quando o limite acaba, os próximos itens registram AudD bloqueado e ainda podem consultar fontes gratuitas.

Respostas de cache não fazem reserva. Requisição cuja entrega ficou incerta mantém a reserva, pois pode ter sido processada no servidor. O contador mostra tentativas reservadas, não cobranças confirmadas. Esse controle não é um teto mensal da conta: outras execuções, programas ou tokens podem consumir a assinatura separadamente.

O padrão é AudD desmarcado e limite 0. O token sozinho não ativa cobranças. O usuário escolhe a fonte, o limite e inicia a identificação. Cache positivo e negativo seguem os TTLs do projeto; nenhum segredo ou trecho de áudio é salvo no cache.

## Paralelismo

Até quatro músicas podem estar ativas; o padrão é duas. Cada música pode consultar provedores distintos em paralelo. O ramo AcoustID consulta MusicBrainz assim que recebe MBIDs, sem esperar ShazamIO ou AudD.

| Provedor | Agendamento local compartilhado pelo lote |
|---|---|
| AcoustID | Uma chamada ativa, início de chamadas com intervalo mínimo de 0,35 s. |
| MusicBrainz | Uma chamada ativa, intervalo mínimo de 1,05 s. |
| ShazamIO | Uma chamada ativa, intervalo local configurável; padrão 3 s. |
| AudD | Até o número configurado de músicas ativas, sempre limitado pelo orçamento compartilhado. |

O intervalo do ShazamIO é uma escolha conservadora do aplicativo, não uma cota oficial garantida. Não há contrato de throughput fornecido pelo cliente não oficial. Aumentar o número de músicas não cria novas cotas para os serviços.

Esperas não seguram um bloqueio global: outros provedores continuam. Limitação ou indisponibilidade persistente aplica pausa por fonte, inicialmente 60 s, crescendo em reincidências até 15 minutos, e respeitando Retry-After quando maior. Itens que chegam durante a pausa recebem pendência dessa fonte, sem esperar minutos ocupando a fila. Após a pausa, uma nova execução pode tentar as fontes pendentes e reutilizar os demais resultados em cache.

Há cancelamento de tarefas em andamento e nenhuma nova música é agendada após a solicitação. Chamadas HTTP já iniciadas podem esperar o timeout. As respostas são associadas ao UUID do arquivo, independentemente da ordem de conclusão. Consultas simultâneas iguais usam bloqueio por chave e compartilham o resultado em cache no modo normal. Atualizar consultas força reconsulta dentro do orçamento.

As cotas são compartilhadas dentro de uma execução da aplicação; múltiplos processos independentes exigem coordenação adicional, ainda não implementada.

## Ajustes opcionais

Em Serviços e ferramentas…, ajustar Músicas em paralelo (1–4) e Intervalo mínimo ShazamIO (1–300 s). Para persistir apenas parâmetros sem credenciais, adicionar ao TOML:

```toml
[network]
shazam_interval_seconds = 3

[processing]
analysis_workers = 2
audd_max_requests = 0
```

Se essas seções já existem, acrescentar as opções dentro delas, sem duplicar cabeçalhos. O limite de execução também pode ser ajustado diretamente na janela.

## Validação

A suíte determinística passou com 161 testes aprovados e um pulado por restrição local de symlinks. Os testes verificam multipart, token inválido, ausência, falhas sem repetição paga, reserva concorrente, limite zero, cache sem token/orçamento, comparação de três fontes, sobreposição de provedores, intervalos compartilhados, pausa sem bloquear outra fonte e cancelamento. O teste da janela processa dois arquivos em paralelo com limite AudD de uma chamada e confirma um único envio simulado.

As requisições AudD foram simuladas com HTTPX MockTransport; não foi consumida consulta paga real. O token ainda não estava disponível no ambiente da sessão. A validação remota fica para o usuário informar o token no campo mascarado ou no ambiente e executar uma consulta com limite 1. A interface foi aberta offscreen e exibiu os 40 arquivos da pasta já autorizada; captura local em reports/afinario-audd.png.

Linux/macOS ainda aguardam validação prática. Não houve alteração dos arquivos musicais.
