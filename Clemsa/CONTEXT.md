# Contexto guardado

- Equipo: macOS; Homebrew está instalado en `/opt/homebrew/bin/brew`.
- `yt-dlp` se instaló correctamente con Homebrew (versión verificada: `2026.08.19`).
- Los videos descargados con `yt-dlp -t mp4` salían sin sonido porque faltaba FFmpeg.
- `ffmpeg` ya se instaló y se verificó (versión `9.0.2`).
- Para obtener una copia nueva con audio, citar la URL (zsh interpreta `?` como comodín) y volver a descargar, por ejemplo:

  ```bash
  yt-dlp -t mp4 -o "%(title)s - con audio.%(ext)s" "https://youtu.be/H3gH_Fe6xvs?si=EO8C5xPnHPqY92_-"
  ```

- El archivo descargado anteriormente no obtiene audio retroactivamente; la descarga debe repetirse.
