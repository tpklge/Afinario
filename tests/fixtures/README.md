# Áudio sintético para testes

Os arquivos tone.* contêm 0,4 segundo de senoide de 440 Hz gerada localmente com FFmpeg 9.0.2. Não contêm música de terceiros. Os metadados de exemplo e a letra sintética foram adicionados apenas a esses arquivos de teste com Mutagen 1.48.1. MP3/M4A/WAV contêm também uma imagem PNG de um pixel.

São fixtures pequenas e determinísticas para testar leitura, detecção de formato, Unicode, letras e preservação dos bytes. Nenhum teste precisa de FFmpeg para usá-las. Elas não comprovam compatibilidade de escrita em músicas reais ou players.
