# Teste no Windows 11

Guia de 29/10/2026 para testar o código-fonte atual. O instalador com Python e ferramentas incluídos ainda não foi implementado.

## Preparar e abrir

Com Git e uv instalados, abra o PowerShell na pasta onde deseja guardar o projeto:

```powershell
git clone https://github.com/tpklge/Afinario.git
cd Afinario
uv sync --locked --python 3.12 --extra dev --extra recognition --extra gui-test
uv run --no-sync python -m afinario doctor
uv run --no-sync python -m afinario gui
```

Se já houver um clone, abra sua pasta e execute `git pull --ff-only` antes de sincronizar as dependências. O repositório privado exige acesso à conta autorizada no GitHub.

O extra `gui-test` inclui interface, player e ferramentas de teste. O extra `recognition` acrescenta o ShazamIO experimental. Não é necessário ativar o ambiente virtual; depois da instalação, também é possível abrir diretamente com `.\.venv\Scripts\python.exe -m afinario gui`.

FFmpeg, ffprobe e fpcalc são ferramentas externas e ainda precisam estar instalados no Windows. Em **Serviços e ferramentas…**, informe os caminhos dos executáveis quando não estiverem no PATH. FFmpeg e ffprobe dão suporte ao processamento/verificação de áudio; fpcalc é usado pelo AcoustID. O diagnóstico `doctor` informa o que está disponível. Também confira os caminhos na interface, que pode restaurar configurações locais próprias.

Configure suas chaves AcoustID/AudD em **Serviços e ferramentas…** e salve. As credenciais do macOS não acompanham o código: no Windows, ficam no cofre do usuário. Pastas, banco, cache e backups também são locais de cada computador.

## Roteiro de teste

Use uma pasta com cópias das músicas para a primeira homologação:

1. Varra arquivos MP3, M4A, FLAC, Vorbis e Opus disponíveis; confira acentos, capas e duração.
2. Reproduza músicas, altere posição/volume e selecione outra faixa.
3. Identifique usando os serviços configurados. Para AudD, habilite o provedor e defina um limite pequeno de consultas; 0 não envia novas consultas pagas.
4. Confira a aplicação por concordância: nome, artista/título, letras ausentes e histórico de backups. Exercite também a aprovação manual de campos.
5. Pause um lote, feche a janela, abra novamente e retome em **Lotes e relatórios**. Confira os itens processados e o uso AudD preservado.
6. Exporte JSON/CSV e restaure uma alteração em **Aplicar e restaurar → Backups e restauração**. Se houve várias operações na mesma música, restaure da mais recente para a mais antiga.
7. Confira caminhos com espaços e acentos, nomes longos e arquivos temporariamente abertos em outro programa. Falhas devem aparecer com motivo, preservando os arquivos.

Para executar a suíte automatizada sem janela:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
uv run --no-sync python -m pytest
Remove-Item Env:QT_QPA_PLATFORM
```

A variável `QT_QPA_PLATFORM` deve estar removida antes de abrir a interface normalmente. Os testes usam dados isolados, sem chamadas reais aos provedores. Para testes de escrita de tags e restauração de áudio, FFmpeg precisa estar disponível no PATH; alguns testes são pulados quando ele não está disponível.

Ao registrar um problema, inclua formato, ação, mensagem exibida e versão do código (`git rev-parse --short HEAD`). Relatórios exportados incluem caminhos/metadados locais; compartilhe somente o necessário. Tokens não são necessários para diagnosticar mensagens.
