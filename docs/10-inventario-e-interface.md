# Inventário e interface — itens 4 e 5

## Entrega

Inventário somente leitura e interface Qt Widgets em português. A varredura não faz consultas externas, não utiliza FFmpeg e não exige credencial. A ação Identificar foi acrescentada posteriormente nos itens 6 a 8, conforme [Reconhecimento](11-reconhecimento-e-resolucao.md). Atualização: a [persistência da biblioteca](13-persistencia-da-biblioteca.md), antigo item 3, está implementada. Fechar e reabrir restaura o inventário e as propostas; respostas de provedores continuam em um cache separado.

## Abrir

Linux/macOS, após instalar Python e uv:

```bash
uv sync --locked --extra gui
uv run --no-sync python -m afinario gui
```

No ambiente Windows já preparado:

```powershell
.\.venv\Scripts\python.exe -m afinario gui 'G:\USR\MUSIC\ANIMES MUSICAS OK'
```

Também existe o executável de ambiente `afinario-desktop`. Argumentos posicionais pré-carregam pastas; a varredura só começa pelo botão. A interface contém adicionar/remover origens, subpastas, seleção de formatos, busca textual, tabela, detalhes dos metadados, ocorrências de acesso e cancelamento.

## Comportamento

- Examinar arquivos regulares em uma passagem e interpretar seu conteúdo com Mutagen, sem deixar a extensão escolher o leitor. Um áudio com extensão errada entra com aviso.
- Ler MP3, M4A, FLAC, Vorbis, Opus e WAV com fixtures verificadas; AIFF, WMA, APE e AAC têm leitores disponíveis, ainda sem fixtures de homologação nesta entrega.
- Ler título, artistas, álbum, artista do álbum, faixa/disco, data e gênero quando presentes. Informar presença de letra e quantidade de capas sem carregar letras/imagens na tabela.
- Informar duração, bitrate/taxa de amostragem quando o leitor os fornece. Não inventar campos ausentes. Tags vazias não são preenchidas pelo nome do arquivo.
- Manter arquivos corrompidos como linhas de erro sem abortar os demais. Arquivos não reconhecidos e sem extensão musical são ignorados.
- Deduplicar diretórios e arquivos descobertos por origens sobrepostas. Links simbólicos e junctions encontrados são ignorados; hard links podem aparecer em seus caminhos distintos com aviso.
- Atualizar tabela em lotes de até aproximadamente 50 registros ou intervalos de 100 ms. Usar modelo de tabela, sem widget por célula.
- Cancelar entre arquivos; a leitura do arquivo atual pode terminar antes do cancelamento. Fechar durante a varredura solicita cancelamento e aguarda sem bloquear a thread principal.

A barra é indeterminada durante a leitura porque o total não é conhecido antecipadamente. O rodapé apresenta arquivos examinados, músicas, avisos e falhas. A busca filtra os dados atuais mesmo durante a varredura. Selecionar uma linha abre seus detalhes em texto simples.

## CLI de inventário

```bash
uv run --no-sync python -m afinario scan '/caminho/musicas' --report inventario.json
uv run --no-sync python -m afinario scan '/pasta/a' '/pasta/b' --no-recursive --format MP3 --format FLAC
```

O filtro considera formato real. Para um arquivo corrompido, cuja identificação real é impossível, a extensão determina se ele entra como erro nos formatos selecionados. O relatório contém tags resumidas, caminhos e estatísticas; não inclui letras, capas binárias, credenciais ou áudio. Sua criação não sobrescreve arquivos existentes.

## Evidências desta entrega

Validação em 27/10/2026 no host Windows disponível, Python 3.11.9, Mutagen 1.48.1 e Qt/PySide6 6.12.0.

Foi varrida a pasta autorizada `G:\USR\MUSIC\ANIMES MUSICAS OK`: **40 arquivos examinados, 40 músicas, zero inválidos, zero avisos e zero falhas de acesso**. A leitura de metadados levou aproximadamente 0,046 segundo nessa amostra; esse valor não é uma meta de desempenho. Os 40 arquivos tiveram SHA-256, tamanho e mtime comparados antes/depois, sem diferenças. A janela também concluiu a varredura e exibiu os 40 registros.

Evidências locais, ignoradas pelo Git: `reports/inventory-real-20261028T023159Z.json` e `reports/afinario-inventory.png`. O relatório foi gerado em UTC; o teste ocorreu em 27/10/2026 às 22h31 no fuso America/Cuiaba.

A suíte completa teve **88 testes aprovados e um pulado**, além de lint e formatação aprovados. Os testes usam áudio sintético pequeno incluído em tests/fixtures, sem download de músicas. Cobrem contêineres, Unicode, extensão enganosa, letras/capas, integridade, recursividade, origens sobrepostas, cancelamento, erro de acesso, mudança externa, modelo Qt, busca, detalhes, processamento de eventos e fechamento durante leitura.

Um teste real de symlinks é pulado quando a conta não tem permissão para criá-los; deve rodar nos ambientes Linux/macOS da CI. A matriz desktop está configurada, mas não foi executada remotamente nesta sessão. Não se declara homologação de janelas em Linux/macOS ou compatibilidade de escrita com nenhum formato.

## Próximas dependências

A leitura isolada do inventário gera UUIDs efêmeros; a biblioteca SQLite atribui UUIDs persistentes por caminho ao integrar cada leitura. O reconhecimento integrado à interface e o cache de consultas foram acrescentados nos itens 6 a 8. A base SQLite da biblioteca está implementada. A aprovação por campo está implementada. Retomada persistente de jobs, escritores de tags e desfazer continuam futuros. Não há botão de aplicação.
