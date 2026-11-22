#!/bin/bash
cd "$(dirname "$0")" || exit 1
printf "ID de la extensión (chrome://extensions): "
read -r EXTENSION_ID
python3 torrent_helper.py --extension-id "$EXTENSION_ID"
printf "\nPulsa Intro para cerrar esta ventana."
read -r
