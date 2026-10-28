# Decisões e referências

## Decisões de projeto

| ID | Decisão | Fundamento / situação |
|---|---|---|
| ADR-01 | Aplicação local, Linux prioritário e macOS 15+ posteriormente. | Atualiza a plataforma Windows do roteiro conforme solicitação posterior do usuário; serviços externos apenas para consultas configuradas. |
| ADR-02 | Separar analisar e aplicar. | Permitir revisão, trabalho offline e proteção dos originais. |
| ADR-03 | Preservar diretório original. | Restrição central, aplicada em planejador e executor. |
| ADR-04 | Provedores por adaptadores. | Permitir substituição sem espalhar contratos externos pelo domínio. |
| ADR-05 | SQLite e diário por arquivo. | Retomada auditável sem presumir transação global do sistema de arquivos. |
| ADR-06 | Backup completo antes da mutação. | Recuperar bytes e metadados desconhecidos com fidelidade. |
| ADR-07 | Confianças independentes de identificação e letra. | Falta de letra não impede corrigir uma identificação confirmada. |
| ADR-08 | Python/Qt/Mutagen e ferramentas auxiliares. | Proposta do roteiro, sujeita à prova de integração e revisão de licenças. |
| ADR-09 | Automação desativada inicialmente. | Exige calibração e habilitação explícita antes de escrever sem revisão individual. |
| ADR-10 | Nome proposto Afinário. | Identidade ligada a música e inventário; validação pública pendente. |

## Origem e interpretação

Fonte de requisitos: `g:\USR\DOWNLOADS\roteiro_app_musicas_windows11.md`, recebido para leitura e transformação em documentação. O roteiro não foi alterado. Suas etapas de desenvolvimento são descritas aqui como trabalho futuro, conforme o pedido de produzir somente documentação.

Os documentos detalham contratos, estados, aprovações, leases, política inicial de cache, restrições de links e pontos de recuperação que precisam ser concretizados durante a implementação. Onde o roteiro não fixava valores, parâmetros foram identificados como propostas configuráveis. Após autorização posterior para desenvolver os itens 1 e 2, foram executadas as verificações registradas em [Validação inicial](09-validacao-inicial.md). Isso não valida os recursos futuros de escrita, dispositivos ou distribuição.

## Fontes oficiais indicadas no roteiro

Esta lista preserva as fontes do roteiro para verificação futura. As fontes efetivamente verificadas durante a implementação inicial estão destacadas no documento de validação. Condições comerciais, limites, versões e obrigações de distribuição devem ser conferidos nas fontes primárias vigentes.

| Tema | Referência |
|---|---|
| AcoustID | https://acoustid.org/webservice e https://acoustid.org/faq |
| Mutagen | https://mutagen.readthedocs.io/en/latest/ |
| Qt for Python | https://doc.qt.io/qtforpython-6/ e https://doc.qt.io/qtforpython-6/commercial/index.html |
| Chromaprint | https://github.com/acoustid/chromaprint e https://github.com/acoustid/chromaprint/blob/master/LICENSE.md |
| FFmpeg | https://ffmpeg.org/legal.html |
| ShazamIO | https://github.com/shazamio/ShazamIO |
| LRCLIB | https://lrclib.net/docs e https://github.com/tranxuanthang/lrclib |
| lyrics.ovh | https://github.com/NTag/lyrics.ovh |
| AudD | https://audd.io/ e https://docs.audd.io/ |
| ACRCloud | https://www.acrcloud.com/music-recognition/ e https://docs.acrcloud.com/get-started/tutorials/recognize-music |
| MusicBrainz | https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting |
| PyInstaller | https://pyinstaller.org/en/stable/operating-mode.html |
| Mapeamento de tags | https://picard-docs.musicbrainz.org/en/v3.0/appendices/tag_mapping.html |
| ID3v2.3 | https://id3.org/id3v2.3.0 |
| Caminhos Windows | https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file |

Gratuidade de acesso, licença do cliente, licença do servidor e direitos sobre letras são assuntos diferentes. A escolha de um componente aberto não garante acesso irrestrito ao catálogo de um serviço. A distribuição planejada não inclui banco de letras.
