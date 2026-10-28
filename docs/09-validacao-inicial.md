# Validação inicial — itens 1 e 2

Data local: 27/10/2026, America/Cuiaba. Escopo: viabilidade dos provedores e estrutura técnica. A validação foi executada no host Windows disponível; WSL não está instalado. Nenhuma alteração de sistema para instalar WSL foi realizada.

## Evidências executadas

| Verificação | Resultado | Limite da evidência |
|---|---|---|
| Instalação editável com extras dev e recognition. | Concluída em Python 3.11.9; pip check sem inconsistências. | Não comprova instalação em Linux/macOS. |
| Testes determinísticos e Ruff. | 60 testes aprovados; lint e formatação aprovados. | Não validam cobertura de catálogos externos. |
| Lock e pacote Python. | uv sync --locked concluído; wheel py3-none-any gerado. | Wheel exige Python e não inclui executáveis de áudio. |
| LRCLIB, consulta Coldplay / Yellow. | HTTP válido, 20 candidatos com textos e durações diferentes. | Busca não confirma gravação/versão; seleção futura precisa filtrar duração. |
| lyrics.ovh, Coldplay / Yellow. | Texto retornado, sem evidência de artista/duração na resposta. | Não comprova equivalência à letra de outro provedor. |
| ShazamIO 0.9.0 e shazamio-core 2.0.0. | Silêncio gerado retornou sem correspondência. Após autorização da pasta musical, uma faixa real retornou Some Like It Hot!!, de SPYAIR, na primeira amostra. | Um resultado positivo não mede cobertura nem confirma a versão exata. |
| AcoustID. | Chave configurada pelo usuário; consulta real retornou dois candidatos SPYAIR, ligados ao mesmo MBID, com duração 191,493 s. | Uma música não mede cobertura; score original não é probabilidade de acerto. |
| Ferramentas de áudio. | FFmpeg/ffprobe 9.0.2 e fpcalc 1.6.2 instalados localmente em .tools; duração, fingerprint e extração de amostra executados. | Validação no host Windows; ferramentas não foram instaladas no Linux/macOS. |
| Linux/macOS. | Código sem dependência Win32; matriz de CI preparada. | Não executada remotamente nesta sessão; compatibilidade prática ainda pendente. |

Os JSONs locais ficam em `reports/` (ignorado pelo Git): `lyrics-live.json`, `shazam-synthetic.json`, `doctor.json`, `audio-before.json`, `audio-live.json`, `audio-integrity.json`, `doctor-audio.json`, `audio-dual-20261028T021941Z.json` e `audio-dual-integrity-20261028T021941Z.json`. Não incluem chaves, letras completas nem o fingerprint. Uma música da pasta autorizada pelo usuário foi lida para reconhecimento; nenhum arquivo musical foi modificado ou baixado. O sufixo dos relatórios usa UTC; a execução dupla ocorreu em 27/10/2026 às 22h19, America/Cuiaba.

## Prova com música autorizada

O usuário autorizou usar qualquer música de `G:\USR\MUSIC\ANIMES MUSICAS OK`. Foi selecionado `01 - Samurai Heart (Some Like It Hot!!).mp3`, com 7.661.696 bytes e duração de 191,53 segundos. A execução usou a CLI existente, com `--online` e `--allow-audio-upload`, e uma amostra temporária de até 12 segundos extraída localmente.

Na primeira execução, ShazamIO retornou artista **SPYAIR**, título **Some Like It Hot!!** e identificador **53583593**, na primeira tentativa. AcoustID ficou bloqueado por ausência de chave, registrado no relatório inicial com código de saída 1.

Após o usuário configurar a chave, a execução dupla retornou código de saída **0**, com ambos os provedores respondendo na primeira tentativa. AcoustID retornou artista **SPYAIR**, título **サムライハート(Some Like It Hot!!)**, duração **191,493 segundos** e MBID **4efa6991-a931-4212-95a7-8aee506ae491**. Dois fingerprints do catálogo apontaram para esse mesmo MBID, com scores originais de **0,9720135** e **0,9661458**. Esses scores não representam probabilidades. ShazamIO repetiu artista, título e identificador da execução anterior.

Os resultados são compatíveis no artista e no título compartilhado, apesar da apresentação em idiomas diferentes. Isso foi comparado na revisão desta prova; a CLI ainda não possui resolvedor automático de equivalências multilíngues. A edição exata e o álbum não foram confirmados por referência independente. Não preencher esses campos com base apenas nesse reconhecimento.

O SHA-256 completo foi comparado antes e depois: `5ce538a86706bda58994abbe99d45d772b3fc205ad69896a0de9f3dd54a56c22`. Os bytes, tamanho e mtime permaneceram iguais. Foi gerado fingerprint local, mas ele não foi salvo nos relatórios.

As ferramentas foram baixadas para `.tools/`, ignorada pelo Git, sem modificar o PATH global. O arquivo `afinario.local.toml`, também ignorado, aponta para os executáveis. O ZIP FFmpeg foi obtido de [Gyan](https://www.gyan.dev/ffmpeg/builds/), fornecedor indicado na [página oficial de downloads](https://ffmpeg.org/download.html), com SHA-256 conferido contra o checksum publicado. O fpcalc veio da [release oficial Chromaprint 1.6.2](https://github.com/acoustid/chromaprint/releases/tag/v1.6.2). Origens e hashes locais estão em `.tools/provenance.json`; o hash do fpcalc foi registrado, sem alegar validação contra checksum publicado.

Para repetir no host atual, escolher um nome de relatório ainda inexistente e executar:

```powershell
.\.venv\Scripts\python.exe -m afinario --config afinario.local.toml probe --online --allow-audio-upload --audio 'G:\USR\MUSIC\ANIMES MUSICAS OK\01 - Samurai Heart (Some Like It Hot!!).mp3' --report reports/audio-live-next.json
```

A chave de aplicação foi configurada localmente pelo usuário. A execução carregou a variável do ambiente persistente do usuário para seu processo, sem exibir o valor nem gravá-lo no TOML ou nos relatórios. Não foi criada conta pelo agente nem usada chave pública de terceiros. Novos terminais devem herdar `AFINARIO_ACOUSTID_KEY`; processos anteriores à configuração podem precisar ser reiniciados.

## Fontes verificadas e decisões

- [AcoustID Web Service](https://acoustid.org/webservice): confirmado endpoint de lookup, chave de aplicação, fingerprint/duração total, uso gratuito não comercial e limite de três requisições por segundo. A CLI adota uma chamada por segundo por provedor.
- [ShazamIO](https://github.com/shazamio/ShazamIO) e [metadados 0.9.0](https://pypi.org/project/shazamio/0.9.0/): cliente não oficial, licença MIT e reconhecimento por janela de 12 segundos. Mantido opcional e experimental.
- [LRCLIB](https://github.com/tranxuanthang/lrclib) e [documentação](https://lrclib.net/docs): serviço comunitário e implementação aberta. A prova usou apenas busca; consulta exata e validação da duração ficam para a etapa de letras.
- [lyrics.ovh, contrato oficial](https://github.com/NTag/lyrics.ovh/blob/main/apiary.apib): GET por artista/título, sucesso com texto e 404 sem resultado. Não inventar evidências ausentes.
- [Qt, plataformas suportadas](https://doc.qt.io/qt-6/supported-platforms.html): documentação atual inclui Linux e macOS, com arm64/x86_64. A futura versão de PySide6 precisará ser fixada e testada; Qt não foi instalado nesta etapa.
- [shazamio-core 2.0.0](https://pypi.org/project/shazamio-core/2.0.0/#files): arquivos publicados incluem Linux x86_64/aarch64 e macOS Intel/Apple Silicon. Existência de wheel não comprova o funcionamento no equipamento alvo.

Dependências efetivamente instaladas: HTTPX 0.28.1 (BSD-3-Clause), platformdirs 4.13.6 (MIT), ShazamIO 0.9.0 (MIT). As licenças foram conferidas nos metadados publicados. O metadado de licença do shazamio-core não é suficiente para concluir a revisão de distribuição: inspecionar os avisos do pacote e suas dependências nativas antes de publicar binários. Qt, Mutagen e executáveis não fazem parte do pacote atual e mantêm revisão pendente.

Não foram revalidados preços de provedores comerciais, nem ativadas contas ou cobranças. Não se declara uma licença final do Afinário nesta etapa.

## Situação das entregas

**Item 1: prova funcional dos quatro provedores demonstrada no host disponível.** Letras têm evidência real e os dois reconhecedores retornaram resultados compatíveis para uma música autorizada. Fingerprint, extração de amostra e preservação do original foram verificados. A validação geral continua parcial: falta ampliar a amostra, conferir versões por referência conhecida, executar em Linux/macOS e concluir a revisão de distribuição. Não confundir a prova de dois reconhecedores com cobertura ou compatibilidade já homologadas.

**Item 2: estrutura inicial implementada.** Pacote src, configuração, diagnóstico, logs sanitizados, contratos, adaptadores, testes, lock transitivo e CI estão disponíveis. Persistência musical, interface e aplicação de mudanças são etapas posteriores.

Próximas validações: ampliar a amostra autorizada com versões conhecidas, revisar gravação/versão e instalar as ferramentas nativas para repetir em Linux e macOS, começando pelo alvo Linux. Disponibilidade do serviço e acerto precisam ser registrados separadamente.
