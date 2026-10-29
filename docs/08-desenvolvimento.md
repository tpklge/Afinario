# Desenvolvimento e execução

## Plataforma e limites atuais

O núcleo é Python 3.11–3.13, executado diretamente no sistema. macOS 15 Sequoia ou superior e Windows 11 são os alvos atuais de desenvolvimento. macOS exige validação própria em Apple Silicon e Intel. Linux, inicialmente Ubuntu 24.04 x86_64, continua na matriz. Não usar Wine nem APIs Windows no domínio.

A interface desktop usa Qt Widgets (PySide6-Essentials) e um player local com Qt Multimedia (PySide6-Addons). Os extras gui e gui-test incluem ambos os pacotes. A CLI possui os comandos gui e scan, além de doctor e probe. A janela também reconhece áudio e compara candidatos. A biblioteca usa SQLite com migrações e restauração automática; o cache de consultas tem SQLite separado. Consulte [Persistência](13-persistencia-da-biblioteca.md) para os locais de dados, recuperação e precedência das preferências. A aba Aplicar e restaurar grava campos aprovados, renomeia com concordância suficiente e permite restaurar backups; veja [Aplicação](16-planejamento-aplicacao-e-restauracao.md). Consulte [Inventário e interface](10-inventario-e-interface.md) e [Reconhecimento](11-reconhecimento-e-resolucao.md).

## Instalação reprodutível com uv

Instale Python e uv 0.13.6. Na raiz do projeto:

```bash
uv sync --locked --extra dev --extra recognition --extra gui-test
uv run --no-sync afinario doctor
uv run --no-sync afinario gui
```

O uv.lock inclui resolução e hashes de dependências transitivas com marcadores de plataforma. `--locked` recusa alterações necessárias no lock. O extra `recognition` instala ShazamIO e sua extensão nativa. O extra `gui` instala somente a interface; `gui-test` acrescenta pytest-qt para testes. Mutagen é dependência do inventário. Use `--no-sync` nos comandos seguintes à instalação para preservar os extras selecionados.

Alternativa com pip no Linux/macOS, sem aplicar o lock transitivo do uv:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,recognition,gui-test]'
.venv/bin/python -m afinario doctor
```

No PowerShell, o interpretador equivalente é `.venv\Scripts\python.exe`. Não é necessário ativar o ambiente virtual.

## Ferramentas de áudio

Ubuntu/Debian: instalar os pacotes `ffmpeg` e `libchromaprint-tools` pelo gerenciador do sistema. macOS: com Homebrew previamente instalado, instalar `ffmpeg` e `chromaprint`. O diagnóstico precisa encontrar `ffmpeg`, `ffprobe` e `fpcalc`.

Esses pacotes externos não são baixados automaticamente pelo aplicativo nem fixados pelo uv.lock. Executar `doctor` registra suas versões reais. Distribuição, licença e diferenças de compilação serão verificadas antes do empacotamento.

Copie `afinario.example.toml` para `afinario.local.toml` para configurar caminhos e rede. O arquivo local é ignorado pelo Git. Uso:

```bash
uv run --locked afinario --config afinario.local.toml doctor
```

Os comandos doctor, probe e scan usam padrões internos quando `--config` não é informado. A interface gui e afinario-desktop carregam `afinario.local.toml` da pasta de execução se existir; `--config` explícito prevalece. Esse arquivo local é configuração confiável do usuário e pode indicar executáveis. Credenciais não são aceitas no TOML nem são gravadas no banco. Configuração TOML tem precedência sobre parâmetros salvos pela interface; sem TOML, parâmetros públicos salvos no mesmo sistema são restaurados. A chave AcoustID vem do cofre nativo, de `AFINARIO_ACOUSTID_KEY` ou do diálogo de serviços, que agora permite salvar no cofre. No Windows, há fallback de leitura da variável persistente do usuário para IDEs abertas antes da configuração. Não usar chave de submissão. Keychain no macOS e WinVault no Windows persistem as credenciais fora do projeto; Secret Service é o backend adicional no Linux. Valores salvos prevalecem sobre o ambiente; campos salvos vazios desativam o serviço.

## Prova de letras

```bash
uv run --locked afinario probe --online --artist Coldplay --title Yellow
```

Consulta LRCLIB por busca e lyrics.ovh pelo endpoint artista/título. Retorna candidatos normalizados, sem escolher automaticamente a letra correta. Correspondência exata, duração e resolução de conflitos serão implementadas nas etapas seguintes.

## Prova de reconhecimento

Defina a variável de ambiente com sua chave de aplicação AcoustID no terminal local. Selecione um arquivo que você possui e autoriza a consultar:

```bash
uv run --locked afinario probe --online --audio '/caminho/musica.mp3'
```

Esse comando envia fingerprint e duração ao AcoustID. Para testar também o ShazamIO experimental:

```bash
uv run --locked afinario probe --online --allow-audio-upload --audio '/caminho/musica.mp3'
```

O ShazamIO processa um trecho local de até 12 segundos e envia sua representação de reconhecimento ao serviço. `--allow-audio-upload` é a autorização explícita para usar o conteúdo da amostra com esse provedor, mesmo que o cliente transmita uma assinatura derivada em vez do WAV. Um segundo trecho distinto só é tentado quando o primeiro retorna ausência de correspondência. Falha de rede ou autenticação não dispara uma segunda amostra.

Cada reconhecimento Shazam roda em subprocesso com prazo total e fechamento do cliente. Os trechos são temporários fora da biblioteca. AudD está disponível na interface com token e orçamento por execução, conforme [AudD e paralelismo](12-audd-e-paralelismo.md). O comando probe continua sendo a prova das fontes gratuitas, sem ativar AudD implicitamente. Não há escrita no arquivo original.

É possível combinar `--artist`, `--title` e `--audio` para consultar as quatro fontes no mesmo relatório. O artista/título informado é apenas a entrada do teste de letras; não é derivado nem confirmado automaticamente pelos resultados de áudio.

## Relatórios e códigos de saída

Acrescente `--report caminho-novo.json` a `doctor`, `probe` ou `scan`. O diretório pai deve existir. O comando cria arquivo exclusivamente e recusa sobrescrever qualquer arquivo existente, inclusive músicas. O relatório também é impresso na saída padrão. A interface exporta CSV/JSON pela aba **Lotes e relatórios**, conforme [Automação, lotes e relatórios](17-automacao-lotes-e-relatorios.md).

Relatórios não contêm texto completo de letras, fingerprint, amostras de áudio ou credenciais. O diagnóstico local contém caminhos de dados do usuário; revisar antes de compartilhar.

| Código | Significado |
|---|---|
| 0 | Doctor executado; probe com candidatos em todas as fontes; ou scan sem arquivos inválidos/falhas de acesso. |
| 1 | Probe parcial/sem resultado, ou scan com arquivos inválidos/falhas de acesso. Conferir o JSON. |
| 2 | Uso/configuração inválidos ou impossibilidade de gravar relatório. |
| 130 | Interrupção pelo usuário. |

Doctor pode retornar 0 mesmo com ferramentas ausentes: sua função é diagnosticar. Um provedor retornar candidatos não comprova acerto. `two_audio_recognizers_returned_candidates` indica apenas que ambos retornaram candidatos, sem comprovar concordância entre eles.

## Estrutura atual

| Arquivo | Papel |
|---|---|
| src/afinario/cli.py | Comandos, validação de opções e relatórios. |
| config.py / logging_config.py | TOML, caminhos nativos e sanitização de logs. |
| domain.py | Candidatos e resultado normalizado. |
| transport.py | HTTP, limites por provedor, tentativas e categorias de erro. |
| providers.py | LRCLIB, lyrics.ovh e AcoustID. |
| audio.py | Execução local de fpcalc, ffprobe e FFmpeg. |
| probe.py / shazam_worker.py | Orquestração da prova e isolamento do ShazamIO. |
| diagnostics.py | Versões, ferramentas, plataformas e caminhos. |
| identification.py / resolver.py | Orquestração por arquivo, comparação e decisões por evidência. |
| metadata.py / provider_cache.py | MusicBrainz e cache persistente de respostas normalizadas. |
| audd.py | Endpoint AudD standard e reserva atômica de consultas por lote. |
| cancellation.py | Cancelamento e execução limitada de processos auxiliares. |
| inventory.py | Descoberta local, formatos reais, tags, estatísticas e cancelamento. |
| library.py / ui/library_worker.py | Biblioteca SQLite, migrações, snapshots, lotes, propostas, preferências e restauração fora da thread da interface. |
| credentials.py | Cofre nativo por usuário, com substituição das credenciais em uma entrada. |
| lyrics.py / review.py / ui/review_panel.py | Busca/importação, comparação e aprovação versionada por campo. |
| ui/ | Interface Qt, modelo de tabela e worker em segundo plano. |
| tests/ | Testes determinísticos, sem chamadas externas. |

## Verificação

```bash
uv run --no-sync python -m ruff check .
uv run --no-sync python -m ruff format --check .
uv run --no-sync python -m pytest
uv run --no-sync python -m afinario doctor
```

A CI está configurada para o núcleo no Ubuntu 24.04, macOS 15 e Windows, em Python 3.11–3.13. Reconhecimento e testes desktop offscreen possuem jobs separados nos três sistemas, em Python 3.12. Para testar sem janela em Linux/macOS, definir `QT_QPA_PLATFORM=offscreen`; em PowerShell, usar `$env:QT_QPA_PLATFORM = 'offscreen'`. Isso não substitui provas com arquivos e janelas reais em cada arquitetura. Nenhum teste automatizado exige chave ou usa a rede dos provedores.
