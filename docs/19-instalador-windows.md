# Instalador Windows

## Instalar e abrir

O arquivo `dist/installers/Afinario-0.1.0-windows-x64-setup.exe` instala o Afinário em Windows 11 x64. Abra o instalador com dois cliques e siga o assistente em português. A instalação é por usuário, sem exigir privilégios de administrador. Ao terminar, abra **Afinário** no menu Iniciar ou pelo atalho da área de trabalho.

Download: [release v0.1.0](https://github.com/tpklge/Afinario/releases/tag/v0.1.0). A mesma release também reúne os pacotes macOS; o executável e o SHA-256 Windows originais foram preservados. As receitas de ambos os sistemas estão na branch `main`.

Não é necessário instalar Python, Git, uv, Qt ou ferramentas de áudio, nem usar linha de comando. O pacote inclui o runtime Python, Qt Widgets/Multimedia, dependências dos provedores, ShazamIO, FFmpeg, ffprobe e fpcalc. O executável principal é `Afinario.exe`; a pasta `_internal` e `AfinarioWorker.exe` fazem parte do aplicativo e precisam permanecer junto dele.

As chaves AcoustID/AudD são configuradas em **Serviços e ferramentas…**. Credenciais pessoais não acompanham o instalador. Inventário, reprodução e operações de arquivos são locais; consultas aos serviços e busca de letras precisam de internet e das credenciais aplicáveis. As cotas e a assinatura AudD continuam sendo do usuário.

O destino padrão é `%LOCALAPPDATA%\Programs\Afinario`. Biblioteca, cache, preferências e backups permanecem nos locais de dados já utilizados pelo aplicativo, fora da instalação. O desinstalador remove os arquivos e atalhos do programa; não apaga a biblioteca do usuário, suas músicas ou seus backups. Feche o aplicativo antes de atualizar.

Esta primeira build é para validação privada e não tem assinatura Authenticode. O Windows pode apresentar aviso de editor desconhecido. Os avisos de terceiros ficam em `_internal/notices`; assinatura e preparação das fontes/licenças para distribuição pública continuam como tarefas de entrega. Não foi criado instalador macOS nesta etapa.

## Gerar novamente (desenvolvimento)

Em Windows x64 com Git/uv disponíveis, execute na raiz do projeto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/windows/build.ps1
```

Este comando é para quem gera o pacote; o usuário final abre somente o instalador e o aplicativo. O script sincroniza as dependências fixadas no `uv.lock`, verifica hashes SHA-256 dos downloads, prepara recursos explícitos e gera o instalador. O Inno Setup é preparado em `.tools/inno`, com verificação Authenticode do instalador do compilador. O arquivo `.sha256` acompanha o instalador gerado.

A versão vem dos metadados do projeto. PyInstaller está no extra `windows-build`, aplicado apenas em Windows. Os binários auxiliares e suas versões estão fixados em `packaging/windows/downloads.json`. `.tools`, `build`, `dist` e relatórios são ignorados pelo Git. Arquivos pessoais, banco, chaves e `afinario.local.toml` não são entradas da build.

O empacotamento usa duas inicializações sobre os mesmos módulos: `Afinario.exe` sem console e `AfinarioWorker.exe` para o processo isolado do ShazamIO. O pai inicia esse auxiliar sem console e mantém os limites de tempo e o cancelamento existentes. A execução pelo código-fonte em Windows/macOS/Linux mantém seu funcionamento. Ferramentas incluídas são localizadas em relação ao pacote, sem modificar o PATH global; ferramentas personalizadas configuradas explicitamente continuam sendo respeitadas.

## Verificar o pacote

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/windows/smoke.ps1
```

O teste instala em uma pasta temporária com espaços, inicia o executável com somente diretórios de sistema no PATH e desinstala o pacote de teste ao terminar. Recusa executar se já houver uma instalação Afinário registrada, para preservar essa instalação. Os relatórios ficam em `reports/installer-*`.

A verificação abre a janela principal com banco temporário e cofre vazio isolado, carrega Qt Multimedia, executa ffprobe/FFmpeg/fpcalc sobre áudio sintético em caminho Unicode e verifica os imports do ShazamIO em seu executável auxiliar. Nenhuma música da biblioteca ou consulta paga é utilizada. Isso verifica o pacote na máquina de desenvolvimento; uma VM Windows limpa ainda é necessária para homologação independente das bibliotecas de sistema presentes nesta máquina.

O workflow manual **Windows installer** gera e testa o instalador no runner Windows, guardando o pacote e os relatórios como artefatos. Ele não cria release nem publica automaticamente no GitHub.

### Validação local em 29/10/2026

- Suíte de código: **320 aprovados e um pulado**, por restrição da conta à criação de links simbólicos. Ruff, formatação e consistência das dependências passaram.
- Instalador x64 gerado com Python 3.11.9, PyInstaller 6.22.3 e Inno Setup 7.1.1.
- Instalação e desinstalação silenciosas concluídas em pasta temporária, sem administrador.
- Executável instalado abriu a janela principal e a biblioteca SQLite temporária com sucesso, com `python_on_path=false`.
- FFmpeg, ffprobe e fpcalc incluídos processaram áudio sintético em caminho Unicode. Qt Multimedia e o executável auxiliar ShazamIO carregaram sem ferramentas externas no PATH.
- Nenhuma consulta online ou escrita na biblioteca real foi iniciada. O relatório local é `reports/installer-bundle-check.json`; a CI remota e uma VM limpa ainda não foram executadas nesta entrega.

## Referências da implementação

- [PyInstaller: execução sem console e opções de empacotamento](https://pyinstaller.org/en/stable/usage.html).
- [Inno Setup: compilador e instaladores oficiais](https://jrsoftware.org/isdl.php) e [verificação de assinatura](https://jrsoftware.org/isdl-verify.php).
- [FFmpeg: build Windows utilizada](https://www.gyan.dev/ffmpeg/builds/).
- [Chromaprint: versão 1.6.2](https://github.com/acoustid/chromaprint/releases/tag/v1.6.2).
