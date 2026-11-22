# Contexto de la sesión

## REA en OpenCode

- Se instaló y configuró REA para OpenCode tras aprobar el plan de setup.
- Se usó `rea-agents@6.7.0` (la versión `latest` disponible al configurar).
- Registro MCP: `/Users/ricardogarcia/.config/opencode/opencode.jsonc`
  - Comando: `npx -y rea-agents@6.7.0 mcp`
  - Se creó una copia de seguridad en
    `/Users/ricardogarcia/.config/opencode/opencode.jsonc.rea.backup`.
- Skill REA instalado en:
  `/Users/ricardogarcia/.agents/skills/reverse-engineer-anything`
- Verificación de `rea doctor --client opencode --skill --json`: saludable;
  registro y skill alineados.
- También se inició el servidor MCP, se completó el handshake y `tools/list`
  devolvió 207 herramientas.
- El Node del sistema era v16.13.0, incompatible con REA. Con aprobación se
  instaló Node 22 mediante Homebrew; la versión verificada fue v22.23.3.
- **Pendiente para usar REA en el agente:** reiniciar OpenCode para que cargue
  el registro MCP.

No se instaló ni configuró ningún motor de análisis nativo (Hopper, Ghidra,
IDA, etc.).
