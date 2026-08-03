# Notas para Claude Code en este repositorio

## Bloqueo conocido: push de GitHub en sesiones remotas (Claude Code on the web)

En las sesiones remotas de Claude Code sobre `ares-core/mirofish`, la integración de
GitHub de esta cuenta puede no tener **ningún** permiso de escritura de referencias
sobre el repo, incluso cuando las instrucciones de la sesión piden desarrollar y
pushear a una rama designada. Esto se manifiesta como `403 Resource not accessible
by integration` en **todas** estas vías, de forma consistente y repetible:

- `git push` directo (vía el proxy git local de la sesión)
- `mcp__github__fork_repository`
- `mcp__github__create_repository`
- `mcp__github__create_branch`
- `mcp__github__push_files` (que internamente intenta crear la rama si no existe)

No es un problema de red transitorio ni de firma de commit (autor/email) — reintentar
el mismo comando produce el mismo 403. No hay forma de rodear esto desde la sesión:
ninguna combinación de herramientas de git/GitHub disponibles tiene permiso de
`git/refs` sobre este repo cuando ocurre.

### Procedimiento a seguir si esto vuelve a pasar

1. **No insistir indefinidamente.** Confirmar el bloqueo con 1-2 reintentos (incluyendo
   al menos una vía distinta, p. ej. `git push` y `mcp__github__create_branch`), y si
   ambas fallan igual, asumir que es el mismo bloqueo de permisos de la integración.
2. **No hacer commits/push a `main` ni a otra rama como workaround** — eso violaría
   las instrucciones de alcance del repo.
3. **Nunca perder el trabajo.** Dejar todo commiteado localmente en la rama designada,
   con autor `Claude <noreply@anthropic.com>` (usar
   `git config user.email noreply@anthropic.com && git config user.name Claude` antes
   de commitear, para que el commit salga verificado si el hook de la sesión lo pide).
4. Generar un parche aplicable con `git format-patch <rama-base> -o <scratchpad>/` y
   entregarlo con `SendUserFile` para que el usuario pueda aplicarlo
   (`git am 0001-*.patch`) en cuanto tenga un entorno con permisos de escritura, o
   pueda revisar/ajustar los permisos de la integración de GitHub conectada a la sesión.
5. Explicar el bloqueo al usuario en términos concretos (qué herramientas fallaron, con
   qué error) en vez de reportar el trabajo como "publicado" o "hecho" sin más.
6. Si el usuario confirma que corrigió los permisos, reintentar `git push` (o
   `create_branch` + `push_files`) antes de volver a generar un parche.
