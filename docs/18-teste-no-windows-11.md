# Teste no Windows 11

Guia de 29/10/2026 para testar o código-fonte atual. Para instalação sem Python ou terminal, veja o [instalador Windows](19-instalador-windows.md).

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

## Validação executada em 29/10/2026

Execução nativa em Windows 11 Pro x64, build 26100, Python 3.11.9 e Qt/PySide6 6.12.0, sobre o commit 576521f e dois ajustes locais de portabilidade nos testes. Dependências sincronizadas pelo uv.lock, incluindo keyring e Qt Multimedia. FFmpeg 9.0.2, ffprobe e fpcalc 1.6.2 ficaram disponíveis no PATH apenas dos processos de teste e da aplicação.

Resultado: **316 testes aprovados e um pulado** pela falta de permissão da conta para criar links simbólicos. Escrita/renomeação, backups, restauração, recuperação de interrupções, persistência, relatórios, credenciais e interface foram exercitados pela suíte em dados isolados. Ruff, formatação e consistência das dependências passaram. Relatório local: `reports/windows-tests-20261029.xml`, ignorado pelo Git.

Dois testes trazidos do macOS precisaram de ajustes: usar entrada/saída binária delimitada por NUL em git check-ignore para evitar conversão CRLF, e ler relatórios JSON explicitamente como UTF-8 em vez da codificação padrão do Windows. Não houve alteração no comportamento do aplicativo para essas correções.

Após os testes, a interface foi iniciada normalmente, com janela nativa visível e responsiva. Não foram iniciadas consultas pagas ou operações de escrita na biblioteca musical real. A validação automatizada não substitui os testes manuais de reprodução, dispositivos e instalador descritos acima.

## Ajustes de compatibilidade Windows/macOS

- Os testes de arquivos ignorados pelo Git usam protocolo binário delimitado por NUL, evitando a conversão CRLF do Windows e mantendo o mesmo comportamento no macOS/Linux.
- Os testes leem relatórios JSON explicitamente em UTF-8, incluindo acentos e caracteres japoneses, sem depender da codificação padrão do sistema.
- O diagnóstico das ferramentas locais usa a opção de processo sem console no Windows, como os demais auxiliares de áudio. No macOS/Linux, essa opção não é enviada. Caminhos continuam sendo argumentos separados, sem interpretação por shell.
- A CI mantém Windows, macOS 15 e Linux. O job desktop exige FFmpeg/ffprobe no PATH antes dos testes, para impedir que a ausência dessas ferramentas oculte a validação de escrita e recuperação; os resultados JUnit ficam disponíveis como artefatos por plataforma.

Os testes reais de biblioteca e identificação relatados pelo usuário foram aceitos conforme a [atualização do plano](06-plano-e-validacao.md). Esta preparação mantém uma única base de código; a execução local nesta máquina verifica Windows, enquanto a execução em macOS é responsabilidade do respectivo job da CI ou de uma máquina macOS.

Após esses ajustes, a suíte completa passou novamente no Windows: **317 testes aprovados e um pulado**, ainda por restrição da conta à criação de links simbólicos. O teste adicional verifica a execução do diagnóstico sem console auxiliar, argumentos com espaços/Unicode e ausência de credenciais no resultado. Ruff e formatação passaram. Relatório local: `reports/windows-compatibility-20261029.xml`. Os novos jobs da CI não foram executados remotamente nesta preparação.
