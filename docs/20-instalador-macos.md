# Instalador macOS

Entrega de 29/10/2026, sobre o commit Windows `af96796`. Os ajustes de portabilidade e o instalador Windows foram incorporados antes desta implementação.

## Instalar e executar

O pacote é para **Apple Silicon (arm64), macOS 15 ou superior**. São geradas duas alternativas em `dist/installers`:

- `Afinario-0.1.0-macos-arm64.pkg`: abra com dois cliques e siga o assistente. Instala em `/Applications/Afinario.app`; a instalação no diretório do sistema pode pedir autenticação de administrador.
- `Afinario-0.1.0-macos-arm64.dmg`: abra a imagem, arraste `Afinario.app` para **Applications** e ejete a imagem. Também é possível copiar para a pasta `Applications` do próprio usuário.

Escolha uma das opções. Feche o aplicativo antes de atualizar e execute a cópia instalada, em vez da cópia dentro da imagem montada. O aplicativo aparece como **Afinário** e inclui Python, Qt Widgets/Multimedia, bibliotecas, ShazamIO, FFmpeg, ffprobe e fpcalc. Não exige instalação de Homebrew, Git, uv ou Python no computador de destino.

Esta build é para validação privada. O aplicativo usa assinatura ad hoc e o instalador não tem assinatura Developer ID Installer nem notarização Apple. Se o macOS bloquear a abertura, confira a origem e use **Abrir Mesmo Assim** em **Ajustes do Sistema → Privacidade e Segurança**. Não é necessário desativar o Gatekeeper. Não há certificado Developer ID disponível nesta máquina para uma distribuição notarizada.

Chaves AcoustID/AudD são configuradas em **Serviços e ferramentas…** e continuam no Keychain do usuário. Credenciais, banco, cache, configurações locais e músicas não são entradas da build. O aplicativo mantém os dados nos locais existentes de `Application Support`, `Caches` e `Logs`; excluir o aplicativo não apaga biblioteca, músicas ou backups. Consultas aos provedores continuam dependendo da internet e das contas/cotas do usuário.

## Compatibilidade e componentes

O runtime é CPython 3.12 gerenciado por uv, com suporte mínimo declarado macOS 11. Não é copiado o Python do Homebrew desta máquina, que exige macOS 26. A build usa PyInstaller 6.22.3 e o extra `macos-build`.

No macOS, Qt/PySide6/Shiboken ficam fixados em **6.11.3**. Os bindings da distribuição 6.12.0 examinada declaram macOS 26 nos comandos Mach-O, apesar da tag de wheel mencionar macOS 14. A versão Mac foi separada por marcadores de plataforma; Windows e Linux mantêm **6.12.0**. A validação confere os binários, em vez de confiar somente na tag da wheel.

FFmpeg/ffprobe 9.0.2 são compilados das fontes fixadas por SHA-256, sem rede nem dependências externas e com alvo macOS 15. A configuração é dedicada ao áudio usado pela aplicação: decodificação dos formatos inventariados, extração PCM, hashes por stream e codificação FLAC para a prova do pacote. Não se trata de uma distribuição geral de FFmpeg para conversão de vídeo. fpcalc 1.6.2 vem do binário oficial AcoustID arm64, com hash verificado.

O processo separado `AfinarioWorker` acompanha o aplicativo e preserva timeout/cancelamento do ShazamIO. Ferramentas são localizadas dentro de `Contents/Frameworks/tools`. Preferências serializam ferramentas incluídas por nome, permitindo mover o aplicativo da imagem para Aplicativos sem conservar caminhos da imagem. Caminhos personalizados explícitos continuam sendo respeitados.

O aplicativo inclui avisos/licenças em `Contents/Resources/notices`, as fontes FFmpeg/Chromaprint e a receita FFmpeg. Antes de distribuição pública, ainda é necessário consolidar fontes/receitas correspondentes de todas as dependências, licença do projeto e assinatura/notarização. Os artefatos e recursos de build são ignorados pelo Git; a receita e o lock são versionados.

## Gerar novamente

Em um Mac Apple Silicon com uv, Command Line Tools e SDK macOS compatível:

```bash
bash packaging/macos/build.sh
```

O script usa o ambiente isolado `.tools/macos-venv` e preserva o ambiente de desenvolvimento `.venv`. O Python de build é gerenciado por uv. A compilação prefere o SDK macOS 15 instalado; `SDKROOT` pode indicar um SDK explicitamente. As dependências Python estão no `uv.lock`; URLs e hashes das ferramentas estão em `packaging/macos/downloads.json`.

Recursos e logs ficam em `build/macos*`. A montagem final usa uma pasta temporária fora do checkout, evitando metadados Finder/file-provider de diretórios sincronizados. O processo verifica arquitetura arm64, versão mínima de cada Mach-O, ausência de referências a bibliotecas Homebrew/fora do sistema e assinatura do aplicativo antes de criar os arquivos. O `.pkg` contém requisitos de arquitetura e macOS 15, sem scripts de instalação personalizados. Há arquivos SHA-256 e manifesto de build junto aos artefatos.

Para verificar os artefatos finais:

```bash
PYTHONPATH=src .tools/macos-venv/bin/python packaging/macos/smoke.py
```

O teste expande o payload `.pkg`, monta o DMG somente para leitura e copia o aplicativo para uma pasta temporária com espaços e Unicode. Cada cópia abre a janela com banco/cofre de teste, carrega áudio no player, executa ferramentas incluídas, grava tags/renomeia com backup, restaura os bytes originais e carrega ShazamIO no processo auxiliar. O PATH contém somente diretórios do sistema, sem Python/Homebrew. Não instala em `/Applications`, não usa serviços online e não acessa as credenciais/músicas do usuário. Relatórios ficam em `reports/macos-*-check.json`.

## Validação

Suíte local com Python 3.12 e Qt 6.11.3: **323 testes aprovados**, incluindo resolução de ferramentas nos dois sistemas e persistência após mover o aplicativo. Ruff e formatação verificados. O aplicativo congelado passou na prova nativa de janela/player, fingerprint, escrita, backup e restauração byte a byte, sem Python no PATH. A auditoria examinou **75 binários Mach-O**, todos arm64 e com versão mínima compatível com macOS 15, sem dependências dinâmicas externas às bibliotecas de sistema ou ao aplicativo.

A execução foi feita neste Mac com macOS 26.7. A análise do alvo mínimo não substitui homologação em um Mac macOS 15 limpo. Macs Intel precisam de outra build e não são atendidos por este instalador arm64. Não foi executado novamente o instalador Windows nesta sessão.

Os dois artefatos finais também passaram no teste: o aplicativo foi executado tanto a partir do payload expandido do `.pkg` quanto de uma cópia instalada do `.dmg`, com banco temporário, sem Python/Homebrew no PATH e com restauração exata do áudio sintético. A imagem foi verificada e desmontada após o teste.

Referências: [PyInstaller macOS](https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support), [Qt: plataformas suportadas](https://doc.qt.io/qt-6/supported-platforms.html), [Python gerenciado por uv](https://docs.astral.sh/uv/concepts/python-versions/), [Chromaprint](https://acoustid.org/chromaprint) e manuais locais `pkgbuild(1)`, `productbuild(1)` e `hdiutil(1)`.
