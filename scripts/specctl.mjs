#!/usr/bin/env node
/**
 * specctl.mjs — CLI única do sistema SPEC (SDD v4)
 * Versão: 4.1.0 · schema: sdd-4.0 · Node >= 18 · zero dependências · Windows/macOS/Linux
 *
 * Mapa de comandos:
 *   init [--force]                      cria estrutura docs/, manifesto e .gitignore
 *   new <slug> [--future] [--porte P|M|G] [--owner @x] [--features a,b] [--program p] [--workspace w]
 *                                       (em main/master só --future — SPEC ativa exige branch de feature, R.2)
 *   activate <id> [--branch b]          future/ -> active/ (claim + [ativação])
 *   pause <id> --motivo "..."           active/ -> future/ (Status: paused)
 *   resume <id>                         future/ -> active/ (recria claim)
 *   reopen <id> --motivo "..."          archive/ -> active/ (correção R.6.2: fechamento indevido; discard não reabre)
 *   archive <id>                        valida fechamento e move p/ archive/
 *   discard <id> --motivo "..."         exige justificativa; digest gerado automático; move p/ discard/
 *   lint [--strict] [--target-main]     validações da §8 (erro -> exit 1)
 *   audit [--pr --base <sha>] [--deps] [--main-gate]
 *   index                               regenera INDEX.md + ARCHIVE-INDEX.md + PROGRAMS.md + DEFERRED.md (determinístico)
 *   next [--program <slug>]             próximo trabalho: programas (DAG) + roadmap + backlog não-priorizado
 *   brief [--compact] [--agent <id>]    contexto de SessionStart (stdout); --agent = bundle 1-call p/ subagente
 *   capsule                             cápsula <=800 bytes (UserPromptSubmit)
 *   stamp                               NOW · commit · branch
 *   verify <id> [--all]                 roda `verify:` dos critérios e grava evidência
 *   log <id> <tipo> "título" [--stdin|--body-file <f>]
 *                                       scribe: appenda entrada no ## LOG (rodapé git automático — B1+)
 *   check <id> <n> [--evidence "..."]   estampa critério n (1-based, SEM verify:) com NOW + commit
 *   digest <id> [--stdin|--file <f>] [--fix]
 *                                       gera/valida digest.md ≤2.000B (LF, comentários HTML descontados)
 *   rollup <area>                       MANUAL/opcional: enxuga o auto-load N1 movendo blocos antigos p/ <area>.history.md (alvo 8.000B; não é lintado nem bloqueia)
 *   escalate <id> <M|G>                 Porte one-way (P→M→G) + [nota] no LOG
 *   deescalate <id> <P|M> --cita "..."  rebaixa Porte SÓ com citação literal do usuário
 *   close <id> [--dry]                  fechamento transacional: stage→validate-ALL→apply
 *   guard-read                          HOOK PreToolUse(Read|Grep|Glob) — deny = exit 2 + stderr
 *   guard-write                         HOOK PreToolUse(Write|Edit) — secret-scan pré-write + deny = exit 2 + stderr
 *   stamp-check                         HOOK PostToolUse — {{NOW}}, timestamps ±24h, secret-scan (2ª linha)
 *   session-close                       HOOK Stop — código editado sem journal atualizado
 *   adopt-workspace <id>                snapshot do workspace externo -> pasta da SPEC
 *   entrypoints                         regenera CLAUDE.md/AGENTS.md (bloco projeto preservado)
 *   self-test                           fixtures em diretório temporário (PASS/FAIL por caso)
 *
 * Exit codes: 0 ok · 1 erro/bloqueio · 2 APENAS hooks (deny).
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { spawnSync, execSync } from 'node:child_process';

const VERSION = '4.1.1';
const SCHEMA = 'sdd-4.0';
const SPEC_RE = /^SPEC-\d{8}-\d{4}-[a-z0-9][a-z0-9-]*$/;
const SPEC_REF_RE = /\bSPEC-\d{8}-\d{4}(?:-[a-z0-9][a-z0-9-]*)?\b/g;
const PHASES = ['active', 'future', 'archive', 'discard'];
const STATUS_ENUM = ['draft', 'active', 'paused', 'done', 'discarded'];
const PHASE_STATUS = { active: ['active'], future: ['draft', 'paused'], archive: ['done'], discard: ['discarded'] };
const LOG_TYPES = ['ativação', 'descoberta', 'decisão', 'tentativa', 'blocker', 'unblock', 'refactor', 'nota', 'conclusão'];
// C2 — bloco JIT ESTÁVEL (sem NOW, ≤900B): impresso SÓ por new/activate (close --dry tem o checklist);
// PROIBIDO adicionar output a guard-*/stamp-check — silêncio em sucesso.
const JIT_FACTS = [
  '— fatos do sistema —',
  `tipos de LOG: ${LOG_TYPES.join(' | ')}`,
  'entradas de LOG: node scripts/specctl.mjs log <id> <tipo> "título" [--stdin|--body-file <f>] — nunca Edit direto no ## LOG',
  'critérios: node scripts/specctl.mjs check <id> <n> (porte P) · node scripts/specctl.mjs verify <id> (M/G)',
  'fechar: node scripts/specctl.mjs close <id> --dry primeiro',
  'digest/bytes: a ferramenta mede — nunca conte',
].join('\n');
// C1 — nota auto-doc do stub de digest (strippada pelos injetores, DESCONTADA do budget via digestMeasure)
const DIGEST_STUB_NOTE = '<!-- ≤2000 bytes LF; a ferramenta mede -->';
// Placeholders do template do SNAPSHOT — presença numa SPEC sendo fechada = SNAPSHOT não atualizado (bug do bench porte-P).
const SNAP_PLACEHOLDER = /início — nada feito ainda|<primeiro passo concreto>|<primeiro passo>|<fase>|<última decisão>/;
const TS_RE = /\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}\b/;
const GERADO_MARK = '> GERADO — specctl index — NÃO EDITAR';
const PROJ_INI = '<!-- projeto:início -->';
const PROJ_FIM = '<!-- projeto:fim -->';

const SECRET_PATTERNS = [
  ['aws-access-key', /\bAKIA[0-9A-Z]{16}\b/],
  ['github-token', /\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b/],
  ['jwt', /\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/],
  ['connection-string', /\b[a-zA-Z][a-zA-Z0-9+.-]{1,24}:\/\/[^\s:@/]{1,64}:[^\s@/]{1,128}@[^\s]{1,256}/],
  ['private-key', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
];

// ---------------------------------------------------------------- utilitários

const P = (...s) => path.join(...s);
const exists = (p) => fs.existsSync(p);
const isDir = (p) => { try { return fs.statSync(p).isDirectory(); } catch { return false; } };
const read = (p) => fs.readFileSync(p, 'utf8');
const readSafe = (p) => { try { return fs.readFileSync(p, 'utf8'); } catch { return ''; } };
const bytesOf = (s) => Buffer.byteLength(s, 'utf8');
const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const norm = (s) => s.replace(/\r\n/g, '\n');
// medição canônica de budget (R.16): bytes LF-normalizados — strip BOM e CR ANTES de medir
const lfText = (s) => String(s).replace(/^﻿/, '').replace(/\r\n?/g, '\n');
const lfBytes = (s) => bytesOf(lfText(s));
// comparação semver simples (a >= b) — gates novos só ativam com template_revision ≥ 4.1.0
function revGte(a, b) {
  const pa = String(a || '0').split('.').map((n) => parseInt(n, 10) || 0);
  const pb = String(b || '0').split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < 3; i++) {
    const x = pa[i] || 0, y = pb[i] || 0;
    if (x !== y) return x > y;
  }
  return true;
}

function writeFile(p, c) { fs.mkdirSync(path.dirname(p), { recursive: true }); fs.writeFileSync(p, c); }
function relOf(root, p) { return path.relative(root, p).split(path.sep).join('/'); }
function pad(n) { return String(n).padStart(2, '0'); }
function now() { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`; }
function nowIdParts() { const d = new Date(); return { date: `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`, time: `${pad(d.getHours())}${pad(d.getMinutes())}` }; }
function parseTs(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/.exec(String(s).trim());
  if (!m) return null;
  return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
}
function die(msg) { process.stderr.write(`[specctl] ERRO: ${msg}\n`); process.exit(1); }
function out(msg) { process.stdout.write(msg + '\n'); }
function splitList(v) {
  if (!v || v.trim() === '—' || v.trim() === '-') return [];
  return v.split(',').map((s) => s.trim()).filter(Boolean);
}
function truncate(s, n) { s = s.trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; }

function scanSecrets(text) {
  const hits = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes('<REDACTED')) continue;
    for (const [tipo, re] of SECRET_PATTERNS) {
      if (re.test(lines[i])) hits.push({ tipo, line: i + 1, lineText: lines[i] });
    }
  }
  return hits;
}

function stripFences(text) { return text.replace(/```[\s\S]*?```/g, '').replace(/<!--[\s\S]*?-->/g, ''); }

function walkFiles(dir, { skipDirs = ['.git', 'node_modules', 'tmp'], exts = null } = {}, acc = []) {
  if (!isDir(dir)) return acc;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const fp = P(dir, e.name);
    if (e.isDirectory()) {
      if (!skipDirs.includes(e.name)) walkFiles(fp, { skipDirs, exts }, acc);
    } else if (!exts || exts.includes(path.extname(e.name).toLowerCase())) {
      acc.push(fp);
    }
  }
  return acc;
}

// ---------------------------------------------------------------- git

function gitRun(args, cwd) {
  const r = spawnSync('git', args, { cwd, encoding: 'utf8' });
  return { ok: !r.error && r.status === 0, out: (r.stdout || '').trim(), err: (r.stderr || (r.error && r.error.message) || '').trim() };
}
// git obrigatório: falha explícita + exit 1 (§15 — nunca engolir erro de git)
function git(args, cwd) {
  const r = gitRun(args, cwd);
  if (!r.ok) die(`git ${args.join(' ')} falhou: ${r.err || '(sem stderr)'} — corrija o estado do git antes de continuar`);
  return r.out;
}
// git opcional (hooks/brief): degrada com AVISO EXPLÍCITO no stderr, nunca silencioso
function gitTry(args, cwd) {
  const r = gitRun(args, cwd);
  if (!r.ok) { process.stderr.write(`[specctl] AVISO: git ${args.join(' ')} falhou: ${r.err || '(sem stderr)'}\n`); return null; }
  return r.out;
}
function currentBranch(root) {
  const a = gitRun(['symbolic-ref', '--short', 'HEAD'], root);
  if (a.ok) return a.out;
  const b = gitRun(['rev-parse', '--abbrev-ref', 'HEAD'], root);
  if (b.ok) return b.out === 'HEAD' ? null : b.out; // detached HEAD: git devolve o literal "HEAD" — não é branch
  process.stderr.write(`[specctl] AVISO: branch git indeterminável: ${a.err || b.err}\n`);
  return null;
}
const DEFAULT_PROTECTED = ['main', 'master', 'develop', 'homolog', 'hmg'];
// branches de integração onde SPEC ativa é PROIBIDA (trabalho sempre em branch própria). Configurável no manifesto.
function protectedBranches(root) {
  try { const m = manifest(root); if (Array.isArray(m.protected_branches) && m.protected_branches.length) return m.protected_branches; } catch { /* sem manifesto: default */ }
  return DEFAULT_PROTECTED;
}
function isProtectedBranch(b, root) { return !!b && protectedBranches(root).includes(b); }
// detecta a branch-base (de onde a feature saiu): a branch protegida ancestral do HEAD, na ordem do manifesto; senão o default do repo
function detectBaseBranch(root, cur) {
  const prot = protectedBranches(root);
  for (const p of prot) {
    if (p === cur) continue;
    if (gitRun(['merge-base', '--is-ancestor', p, 'HEAD'], root).ok) return p; // exit 0 = p é ancestral de HEAD
  }
  const head = gitRun(['rev-parse', '--abbrev-ref', 'origin/HEAD'], root); // ex.: origin/main → main
  if (head.ok && head.out) return head.out.replace(/^origin\//, '');
  return prot.find((p) => p !== cur) || prot[0] || 'main';
}

// ---------------------------------------------------------------- raiz e manifesto

function findRoot(start) {
  let dir = path.resolve(start);
  for (;;) {
    if (exists(P(dir, 'docs', '.spec-system.json')) || exists(P(dir, 'docs', 'RULES.md'))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}
function requireRoot() {
  const r = findRoot(process.cwd());
  if (!r) die('projeto não encontrado — nenhum docs/.spec-system.json (nem docs/RULES.md) subindo a partir de ' + process.cwd());
  return r;
}
function manifest(root) {
  // team: 'solo' (default) | 'multi' — regime DECLARADO, nunca inferido. Em multi: activate imprime a
  // coreografia de publicação do claim, audit avisa claim não-publicado na main, capsule carrega team=multi.
  const def = { schema: SCHEMA, template_revision: VERSION, policy: 'standard', interop: 'none', team: 'solo', product: null, commands: {}, protected_branches: DEFAULT_PROTECTED };
  const p = P(root, 'docs', '.spec-system.json');
  if (!exists(p)) return { ...def, schema: 'sdd-3-compat' };
  try { return { ...def, ...JSON.parse(read(p)) }; }
  catch (e) { process.stderr.write(`[specctl] AVISO: manifesto inválido (${e.message}) — usando defaults\n`); return def; }
}

// ---------------------------------------------------------------- SPECs

function listSpecs(root) {
  const specs = [];
  for (const phase of PHASES) {
    const base = P(root, 'docs', phase);
    if (!isDir(base)) continue;
    for (const e of fs.readdirSync(base, { withFileTypes: true })) {
      if (e.isDirectory()) specs.push({ id: e.name, phase, dir: P(base, e.name), v3: exists(P(base, e.name, 'state.md.v3.bak')) });
    }
  }
  return specs;
}
function activeSpecs(root) { return listSpecs(root).filter((s) => s.phase === 'active'); }
function idPrefix(id) { return id.slice(0, 18); } // SPEC-YYYYMMDD-HHMM
function findSpec(root, id) {
  if (!id) die('informe o id da SPEC (SPEC-YYYYMMDD-HHMM-slug)');
  const all = listSpecs(root);
  const exact = all.find((s) => s.id === id);
  if (exact) return exact;
  const cand = all.filter((s) => s.id.startsWith(id));
  if (cand.length === 1) return cand[0];
  if (cand.length > 1) die(`id ambíguo '${id}' — candidatas: ${cand.map((s) => s.id).join(', ')}`);
  die(`SPEC '${id}' não encontrada em docs/{active,future,archive,discard}/`);
}

// maskFences: cópia das linhas onde conteúdo DENTRO de ``` ```/~~~ e de comentários HTML multi-linha vira ''.
// PRESERVA índices (≠ stripFences, que remove texto): o parser decide sobre a máscara, mas check/verify
// reescrevem a linha ORIGINAL pelo índice. Sem isso, `# comentário` num exemplo bash dentro do main.md
// encerrava a seção de critérios e escondia critério aberto do close/archive/lint (bypass do R.6.2).
function maskFences(lines) {
  const out = [...lines];
  let inFence = false, inHtml = false;
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (inFence) { out[i] = ''; if (/^\s*(```|~~~)/.test(l)) inFence = false; continue; }
    if (inHtml) { out[i] = ''; if (l.includes('-->')) inHtml = false; continue; }
    if (/^\s*(```|~~~)/.test(l)) { out[i] = ''; inFence = true; continue; }
    if (l.includes('<!--') && !l.includes('-->')) { out[i] = ''; inHtml = true; }
  }
  return out;
}
function parseMain(txt) {
  const lines = norm(txt).split('\n');
  const masked = maskFences(lines);
  const fields = {};
  for (const l of masked) {
    const m = /^\*\*([^*]+):\*\*\s*(.*)$/.exec(l);
    if (m && !(m[1].trim() in fields)) fields[m[1].trim()] = m[2].trim();
  }
  const sections = [];
  masked.forEach((l, i) => {
    const m = /^(#{1,6})\s+(.*)$/.exec(l);
    if (m) sections.push({ level: m[1].length, title: m[2].trim(), line: i });
  });
  return { fields, sections, lines, masked, raw: txt };
}
function sectionRange(pm, pred) {
  for (let i = 0; i < pm.sections.length; i++) {
    const s = pm.sections[i];
    if (s.level === 2 && pred(s.title)) {
      let end = pm.lines.length;
      for (let j = i + 1; j < pm.sections.length; j++) {
        if (pm.sections[j].level <= 2) { end = pm.sections[j].line; break; }
      }
      return [s.line, end];
    }
  }
  return null;
}
const isCritTitle = (t) => /^crit[ée]rios? de aceite/i.test(t);
function getCriteria(pm) {
  const r = sectionRange(pm, isCritTitle);
  if (!r) return null;
  const outArr = [];
  const scan = pm.masked || pm.lines; // máscara: checkbox de EXEMPLO dentro de fence não é critério
  for (let i = r[0] + 1; i < r[1]; i++) {
    const m = /^\s*-\s*\[( |x|X)\]\s*(.*)$/.exec(scan[i]);
    if (m) outArr.push({ line: i, checked: m[1].toLowerCase() === 'x', text: m[2], raw: pm.lines[i] });
  }
  return outArr;
}
const hasTs = (l) => TS_RE.test(l);
const hasCommitEv = (l) => /commit\s*`[^`]+`/.test(l);
const hasVerifyTag = (l) => /\bverify:/.test(l);
const hasEvidenceTag = (l) => /\bevidence:/.test(l);
const ACEITO_RE = /\[aceito-incompleto:\s*"[^"]+"\s+\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]/;

function setField(txt, name, value) {
  const re = new RegExp(`^\\*\\*${escRe(name)}:\\*\\*.*$`, 'm');
  if (re.test(txt)) return txt.replace(re, `**${name}:** ${value}`);
  return txt.replace(/^(\*\*Status:\*\*.*)$/m, `$1\n**${name}:** ${value}`);
}

// ---------------------------------------------------------------- templates

function makeMain(o) {
  // D1 — critério scaffoldado por porte: P sem slot verify: (evidência via `check`); M/G mantêm verify:
  const porte = String(o.porte || 'M').toUpperCase();
  const critScaffold = porte === 'P'
    ? '<!-- P: feche com: node scripts/specctl.mjs check <id> <n> -->\n- [ ] <critério binário e verificável>'
    : '- [ ] <critério binário e verificável> | verify: `<comando>`';
  return `# SPEC-${o.idTs}: ${o.title}

**Status:** ${o.status}
**Porte:** ${o.porte}
**Owner:** ${o.owner}
**Criada:** ${o.criada}
**Ativada:** ${o.ativada}
**Concluída:** —
**Pausada em:** —
**Commit final:** —
**Keywords:** ${o.keywords}
**Features:** ${o.features}
**Branch:** ${o.branch}
**Programa:** ${o.programa}
**Workspace:** ${o.workspace}
**Origem:** ${o.origem}
**Resumo:** ${o.resumo}

## Objetivo

<2-3 frases: o quê e por quê.>

## Escopo

**DENTRO:**
- <item>

**FORA:**
- <item>

## Invariantes

<!-- propriedades que valem SEMPRE (antes/durante/depois) — linhas-vermelhas que QUALQUER mudança futura pode violar; distintas dos critérios (que checam o estado final). Estilo SEMPRE/NUNCA. P trivial: "—" -->
- SEMPRE/NUNCA <propriedade que não pode ser violada>

## Implementação

<abordagem em alto nível; porte G: o detalhe fino vai em techspec.md>

### Modelo de dados

<!-- entidades/campos novos ou tocados (schema, tabelas, tipos); "—" se não há mudança de dados -->
| Entidade | Campos / mudança |
|---|---|
| <Entidade> | <campos> |

<!-- Alternativas (M/G): abordagens consideradas e REJEITADAS + porquê — evita reabrir becos sem saída. Decisão irreversível (porta de mão-única): marque [irreversível] p/ sinalizar mais escrutínio. -->

## Riscos

<!-- riscos técnicos/de segurança + mitigação (contrato estável — NÃO é progresso; decisões/fases vão no journal); P trivial: "—" -->
- <risco> — mitigação: <como>

## Sinais de sucesso

<!-- como saberemos que a SPEC cumpriu o PROPÓSITO (não só a corretude dos critérios) — métrica/sinal observável; P: 1 linha -->
- <resultado observável que indica que valeu>

## Critério de aceite

${critScaffold}
`;
}
function makeJournal(idTs, nowStr) {
  return `# Journal — SPEC-${idTs}

## SNAPSHOT (sobrescrever — DEVE caber nas primeiras 60 linhas do arquivo)

**Última atualização:** ${nowStr}
**Onde tô:** início — nada feito ainda
**Próximo passo:** <primeiro passo concreto>
**Última decisão:** —
**Bloqueio atual:** nenhum
**Se retomar, ler:** main.md desta SPEC

### Fases
| # | Descrição | Status | Atualizado |
|---|---|---|---|
| 1 | <fase> | pendente | ${nowStr} |

### Fatos confirmados / Inferências prováveis / Dúvidas em aberto
<!-- anti-alucinação por estrutura: separe o que é SABIDO (verificado no código/teste) do que é CHUTE (inferido) do que está EM ABERTO. Nunca trate inferência como fato. -->
- fato:
- inferência:
- dúvida:

### Respostas-chave do usuário

### Tentativas que falharam

### Arquivos tocados

### Onde parei

### Sessões (máx 5 linhas + 1 agregada)

## LOG (append-only — NUNCA editar entradas antigas)
<!-- tipos: ${LOG_TYPES.join(' ')} | entrada nova: specctl log -->
`;
}
function makeClaim(o) {
  return `# Claim — ${o.id}

**SPEC:** ${o.id}
**Título:** ${o.title}
**Owner:** ${o.owner}
**Branch:** ${o.branch}
**Base:** ${o.base || '—'}
**Features:** ${o.features}
**Ativada em:** ${o.ativada}
`;
}
function appendLog(specDir, tipo, titulo, body = '') {
  const jp = P(specDir, 'journal.md');
  const idTs = path.basename(specDir).slice(5, 18);
  let txt = exists(jp) ? read(jp) : makeJournal(idTs, now());
  txt = txt.replace(/^\*\*Última atualização:\*\*.*$/m, `**Última atualização:** ${now()}`);
  if (!txt.endsWith('\n')) txt += '\n';
  const heading = `## ${now()} — [${tipo}] ${titulo}`;
  txt += `\n${heading}\n`;
  if (body) txt += `\n${body}\n`;
  writeFile(jp, txt);
  return heading;
}
function claimPath(root, id) { return P(root, 'docs', 'claims', `${id}.md`); }
function removeClaim(root, id) { const p = claimPath(root, id); if (exists(p)) fs.unlinkSync(p); }
function moveSpec(spec, root, toPhase) {
  const dst = P(root, 'docs', toPhase, spec.id);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  try { fs.renameSync(spec.dir, dst); }
  catch { fs.cpSync(spec.dir, dst, { recursive: true }); fs.rmSync(spec.dir, { recursive: true, force: true }); }
  ensureGitkeeps(root); // a pasta de origem pode ter ficado vazia — mantém o .gitkeep p/ sobreviver a checkout fresco
  return dst;
}

const REQUIRED_DIRS = ['features', 'active', 'future', 'archive', 'discard', 'claims', 'programs'];
// git não versiona pasta vazia: uma pasta obrigatória vazia (ex.: docs/active/ na main) some num checkout fresco
// e o lint falha "pasta obrigatória ausente". ensureGitkeeps mantém um .gitkeep em toda obrigatória que ficou vazia.
// Idempotente; chamado no init, em toda movimentação de SPEC (moveSpec) e na regeneração de índices (cmdIndex).
function ensureGitkeeps(root) {
  for (const d of REQUIRED_DIRS) {
    const dp = P(root, 'docs', d);
    if (!isDir(dp)) fs.mkdirSync(dp, { recursive: true });
    const hasContent = fs.readdirSync(dp).some((e) => e !== '.gitkeep');
    if (!hasContent && !exists(P(dp, '.gitkeep'))) writeFile(P(dp, '.gitkeep'), '');
  }
}

// ---------------------------------------------------------------- comandos de ciclo de vida

function cmdInit(flags) {
  const root = findRoot(process.cwd()) || process.cwd();
  const manPath = P(root, 'docs', '.spec-system.json');
  if (exists(manPath) && !flags.force) die(`já instalado (${relOf(root, manPath)}) — use --force para regravar o manifesto`);
  for (const d of REQUIRED_DIRS) fs.mkdirSync(P(root, 'docs', d), { recursive: true });
  ensureGitkeeps(root);
  fs.mkdirSync(P(root, '.scratch'), { recursive: true });
  let prev = {};
  if (exists(manPath)) { try { prev = JSON.parse(read(manPath)); } catch { prev = {}; } }
  const man = {
    schema: SCHEMA,
    template_revision: VERSION,
    installed_at: now(),
    policy: prev.policy || 'standard',
    interop: prev.interop || 'none',
    team: prev.team || 'solo',
    product: prev.product ?? null,
    commands: { test: '', typecheck: '', lint: '', dev: '', e2e: '', ...(prev.commands || {}) },
  };
  writeFile(manPath, JSON.stringify(man, null, 2) + '\n');
  const giPath = P(root, '.gitignore');
  const gi = readSafe(giPath);
  const giLines = gi.split(/\r?\n/);
  let giOut = gi;
  for (const line of ['docs/active/**/tmp/', '.scratch/']) {
    if (!giLines.includes(line)) giOut = (giOut && !giOut.endsWith('\n') ? giOut + '\n' : giOut) + line + '\n';
  }
  if (giOut !== gi) writeFile(giPath, giOut);
  // stubs mínimos (não sobrescreve conteúdo instalado pela skill/usuário)
  const taxPath = P(root, 'docs', 'TAXONOMY.md');
  if (!exists(taxPath)) writeFile(taxPath, `# TAXONOMY.md — vocabulário canônico de áreas

> Orçamento-alvo: ≤1.600 bytes. Toda feature de \`docs/features/\` DEVE corresponder a uma área daqui (R.4).
> Área nova = confirmação explícita do usuário (R.13). Namespaces com \`/\` (ex.: \`api/auth\`).
> Formato por linha: \`- <area> — definição 1 linha (aliases proibidos: x→area)\`

## Áreas

<!-- Exemplos — remova ao preencher:
- api/auth — autenticação e sessão do backend (aliases proibidos: login→api/auth, sso→api/auth)
- web/checkout — fluxo de compra no frontend (aliases proibidos: carrinho→web/checkout)
- infra/ci — pipelines de build, teste e deploy (aliases proibidos: actions→infra/ci, gha→infra/ci)
-->
`);
  const constPath = P(root, 'docs', 'CONSTITUTION.md');
  if (!exists(constPath)) writeFile(constPath, `# CONSTITUTION.md — princípios do projeto

> Orçamento-alvo: ≤2.400 bytes. Princípios INEGOCIÁVEIS que valem para TODA SPEC.
> Entrada nova = decisão humana explícita. Gotcha citado por ≥3 SPECs pode ser promovido para cá no fechamento (docs/rules/lifecycle.md).
> Formato: \`- P-<n> — princípio em 1-2 linhas (origem, YYYY-MM-DD)\`

## Princípios

<!-- Exemplos — remova ao preencher:
- P-1 — Toda migração de banco é reversível; PR sem rollback não mergeia (bootstrap, 2026-07-02)
- P-2 — Nenhum segredo em código ou docs; usar env vars e \`<REDACTED:tipo>\` (R.15) (bootstrap, 2026-07-02)
- P-3 — API pública versionada: breaking change exige /v<n+1> (SPEC-20260702-1010-api-v2, 2026-07-02)
-->
`);
  const roadmapPath = P(root, 'docs', 'ROADMAP.md');
  if (!exists(roadmapPath)) writeFile(roadmapPath, `# ROADMAP — ordem de execução do backlog avulso

> Priorização humana das SPECs future SEM programa. Editado por PR dedicado (single-writer).
> SPECs de programa NÃO entram aqui — a ordem delas vem do grafo (docs/programs/).

<!-- Exemplo — substitua pela ordem real (uma SPEC por linha):
1. SPEC-20260702-1010-custom-hostnames
2. SPEC-20260703-0930-audit-log
-->
`);
  // INDEX.md/ARCHIVE-INDEX.md/PROGRAMS.md nascem GERADOS — lint pós-init passa limpo (equivalente a `specctl index` quiet)
  cmdIndex({ quiet: true });
  out(`init ok — estrutura docs/, manifesto (${SCHEMA}), índices gerados e .gitignore em ${root}`);
}

function cmdNew(pos, flags) {
  const root = requireRoot();
  const slug = pos[0];
  if (!slug) die('uso: specctl new <slug> [--future] [--porte P|M|G] [--owner @x] [--features a,b] [--program p] [--workspace w]');
  if (!/^[a-z0-9][a-z0-9-]{0,48}$/.test(slug)) die(`slug inválido '${slug}' — use kebab-case [a-z0-9-]`);
  const porte = String(flags.porte || 'M').toUpperCase();
  if (!['P', 'M', 'G'].includes(porte)) die(`Porte inválido '${flags.porte}' — use P | M | G`);
  const future = !!flags.future;
  const branch = currentBranch(root);
  if (!future && isProtectedBranch(branch, root)) {
    die(`R.2: SPEC ativa é proibida na branch protegida '${branch}' (${protectedBranches(root).join('/')}) — trabalho vive sempre em branch própria. Caminho correto: git checkout -b feature/${slug} e rode o comando lá — ou --future para rascunho em docs/future/.`);
  }
  const { date, time } = nowIdParts();
  const id = `SPEC-${date}-${time}-${slug}`;
  const idTs = `${date}-${time}`;
  const phase = future ? 'future' : 'active';
  const dir = P(root, 'docs', phase, id);
  if (exists(dir)) die(`já existe: ${relOf(root, dir)}`);
  let owner = flags.owner;
  if (!owner) {
    const un = gitTry(['config', 'user.name'], root);
    owner = un ? '@' + un.toLowerCase().replace(/\s+/g, '-') : '@owner';
  }
  const title = slug.replace(/-/g, ' ');
  const mainTxt = makeMain({
    idTs, title,
    status: future ? 'draft' : 'active',
    porte, owner,
    criada: now(),
    ativada: future ? '—' : now(),
    keywords: splitList(flags.features).join(', ') || slug.replace(/-/g, ', '),
    features: flags.features ? splitList(flags.features).join(', ') : '—',
    branch: future ? '—' : (branch || '—'),
    programa: flags.program || '—',
    workspace: flags.workspace || '—',
    origem: `usuário em ${now()}`,
    resumo: '<1 frase sobre o que entrega e por quê>',
  });
  writeFile(P(dir, 'main.md'), mainTxt);
  if (!future) {
    const base = flags.base || detectBaseBranch(root, branch);
    writeFile(P(dir, 'journal.md'), makeJournal(idTs, now()));
    appendLog(dir, 'ativação', `SPEC criada e ativada (${owner}, branch ${branch || '—'}, base ${base})`);
    writeFile(claimPath(root, id), makeClaim({ id, title, owner, branch: branch || '—', base, features: flags.features ? splitList(flags.features).join(', ') : '—', ativada: now() }));
  }
  out(`criada ${relOf(root, dir)} (${future ? 'rascunho em future/ — status draft' : 'ativa — claim registrado'})`);
  if (future) out(`ative com: node scripts/specctl.mjs activate ${id}`);
  out('preencha Objetivo/Escopo/Critério de aceite em main.md — formatos: docs/rules/formats.md');
  out(JIT_FACTS); // C2 — bloco estável (≤900B, sem NOW): permitido SÓ em new/activate/close--dry
}

function cmdActivate(pos, flags) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  if (spec.phase !== 'future') die(`activate: ${spec.id} está em ${spec.phase}/ — só rascunhos em future/ podem ser ativados (pausadas: use resume)`);
  const pm = parseMain(read(P(spec.dir, 'main.md')));
  if (pm.fields.Status === 'paused') die(`${spec.id} está pausada — caminho correto: node scripts/specctl.mjs resume ${spec.id}`);
  const branch = flags.branch || currentBranch(root);
  if (isProtectedBranch(branch, root)) die(`R.2: não ative SPEC na branch protegida '${branch}' (${protectedBranches(root).join('/')}). Caminho correto: git checkout -b feature/<slug> e rode activate lá.`);
  const base = flags.base || detectBaseBranch(root, branch); // branch de onde a feature saiu — usada no fechamento (merge/checkout)
  let txt = read(P(spec.dir, 'main.md'));
  txt = setField(txt, 'Status', 'active');
  if ((pm.fields['Ativada'] || '—') === '—') txt = setField(txt, 'Ativada', now());
  txt = setField(txt, 'Branch', branch || '—');
  writeFile(P(spec.dir, 'main.md'), txt);
  const dst = moveSpec(spec, root, 'active');
  appendLog(dst, 'ativação', `SPEC ativada (branch ${branch || '—'}, base ${base})`);
  const pm2 = parseMain(read(P(dst, 'main.md')));
  writeFile(claimPath(root, spec.id), makeClaim({
    id: spec.id,
    title: (pm2.lines[0] || '').replace(/^#\s*[^:]*:\s*/, '') || spec.id,
    owner: pm2.fields.Owner || '@owner',
    branch: branch || '—',
    base,
    features: pm2.fields.Features || '—',
    ativada: now(),
  }));
  out(`ativada: docs/active/${spec.id} (claim: docs/claims/${spec.id}.md)`);
  // team: multi — o claim precisa correr NA FRENTE do trabalho (visibilidade p/ os outros devs, R.11/team.md)
  if (manifest(root).team === 'multi') {
    out(`— team: multi — PUBLIQUE o claim na ${base} agora (PR trivial, diff só do claim):`);
    out(`  git checkout -b claim/${spec.id} ${base}`);
    out(`  git checkout ${branch || '<branch>'} -- docs/claims/${spec.id}.md`);
    out(`  git commit -m "docs: claim ${spec.id} (R.11)" && git push -u origin claim/${spec.id}`);
    out(`  abra o PR para ${base} (auto-merge se permitido) e volte: git checkout ${branch || '<branch>'}`);
  }
  out(JIT_FACTS); // C2 — bloco estável (≤900B, sem NOW): permitido SÓ em new/activate/close--dry
}

function cmdPause(pos, flags) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  if (spec.phase !== 'active') die(`pause: ${spec.id} está em ${spec.phase}/ — só SPECs ativas podem ser pausadas`);
  const motivo = flags.motivo;
  if (!motivo) die('pause exige --motivo "..." (R.5: pausa preserva contexto com motivo)');
  let txt = read(P(spec.dir, 'main.md'));
  txt = setField(txt, 'Status', 'paused');
  txt = setField(txt, 'Pausada em', `${now()} — ${motivo}`);
  writeFile(P(spec.dir, 'main.md'), txt);
  appendLog(spec.dir, 'nota', `Pausada: ${motivo}`);
  const dst = moveSpec(spec, root, 'future');
  removeClaim(root, spec.id);
  out(`pausada: docs/future/${spec.id} (claim removido). Retome com: node scripts/specctl.mjs resume ${spec.id}`);
  void dst;
}

function cmdResume(pos) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  if (spec.phase !== 'future') die(`resume: ${spec.id} está em ${spec.phase}/ — só pausadas em future/ podem ser retomadas`);
  const pm = parseMain(read(P(spec.dir, 'main.md')));
  if (pm.fields.Status !== 'paused') die(`${spec.id} tem status '${pm.fields.Status}' — rascunhos usam: node scripts/specctl.mjs activate ${spec.id}`);
  const branch = currentBranch(root);
  if (isProtectedBranch(branch, root)) die(`R.2: não retome SPEC na branch protegida '${branch}' (${protectedBranches(root).join('/')}). Caminho correto: git checkout -b feature/<slug> e rode resume lá.`);
  let txt = read(P(spec.dir, 'main.md'));
  txt = setField(txt, 'Status', 'active');
  if (/^\*\*Reativada em:\*\*/m.test(txt)) txt = setField(txt, 'Reativada em', now());
  else txt = txt.replace(/^(\*\*Pausada em:\*\*.*)$/m, `$1\n**Reativada em:** ${now()}`);
  txt = setField(txt, 'Branch', branch || '—');
  writeFile(P(spec.dir, 'main.md'), txt);
  const dst = moveSpec(spec, root, 'active');
  appendLog(dst, 'unblock', 'Retomada (resume)');
  const pm2 = parseMain(read(P(dst, 'main.md')));
  writeFile(claimPath(root, spec.id), makeClaim({
    id: spec.id,
    title: (pm2.lines[0] || '').replace(/^#\s*[^:]*:\s*/, '') || spec.id,
    owner: pm2.fields.Owner || '@owner',
    branch: branch || '—',
    features: pm2.fields.Features || '—',
    ativada: now(),
  }));
  out(`retomada: docs/active/${spec.id} (claim recriado)`);
}

// reopen: rota mecânica da "Aplicação imediata" do R.6.2 (lifecycle §5.1) — SPEC arquivada com pendência
// real volta para active/ SEM mover pastas à mão. Exige --motivo (vai ao LOG; a reabertura fica auditável).
function cmdReopen(pos, flags) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  if (spec.phase !== 'archive') die(`reopen: ${spec.id} está em ${spec.phase}/ — só SPECs arquivadas reabrem (pausada: resume; descartada não reabre, crie SPEC nova citando-a)`);
  const motivo = flags.motivo;
  if (!motivo) die('reopen exige --motivo "..." (por que o fechamento foi indevido — ex.: critério aceito sem autorização R.6.2)');
  const branch = currentBranch(root);
  if (isProtectedBranch(branch, root)) die(`R.2: não reabra SPEC na branch protegida '${branch}' (${protectedBranches(root).join('/')}). Caminho correto: git checkout -b feature/<slug> e rode reopen lá.`);
  let txt = read(P(spec.dir, 'main.md'));
  txt = setField(txt, 'Status', 'active');
  if (/^\*\*Reaberta em:\*\*/m.test(txt)) txt = setField(txt, 'Reaberta em', `${now()} — ${motivo}`);
  else txt = txt.replace(/^(\*\*Criada:\*\*.*)$/m, `$1\n**Reaberta em:** ${now()} — ${motivo}`);
  writeFile(P(spec.dir, 'main.md'), txt);
  const dst = moveSpec(spec, root, 'active');
  appendLog(dst, 'nota', `Reabertura (reopen): ${motivo}`);
  const pm2 = parseMain(read(P(dst, 'main.md')));
  writeFile(claimPath(root, spec.id), makeClaim({
    id: spec.id,
    title: (pm2.lines[0] || '').replace(/^#\s*[^:]*:\s*/, '') || spec.id,
    owner: pm2.fields.Owner || '@owner',
    branch: branch || '—',
    features: pm2.fields.Features || '—',
    ativada: now(),
  }));
  cmdIndex({ quiet: true });
  out(`reaberta: docs/active/${spec.id} (claim recriado, INDEX regenerado)`);
  out(`complete o trabalho e feche de novo: node scripts/specctl.mjs close ${spec.id} --dry`);
}

function featureConcludedOk(root, feat, id) {
  const fp = P(root, 'docs', 'features', ...feat.split('/')) + '.md';
  if (!exists(fp)) return { ok: false, why: `docs/features/${feat}.md inexistente (R.7)` };
  const txt = stripFences(read(fp)); // fences fora: SPEC-id de EXEMPLO num bloco de código não prova R.7
  const pref = idPrefix(id);
  const m = /###\s+Conclu[íi]das([\s\S]*?)(?=\n#{2,3}\s|$)/.exec(txt);
  const scope = m ? m[1] : txt;
  if (!scope.includes(pref)) return { ok: false, why: `R.7: adicione ${pref} em '### Concluídas' de docs/features/${feat}.md (validação por CONTEÚDO)` };
  return { ok: true };
}

function cmdArchive(pos) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  if (spec.phase !== 'active') die(`archive: ${spec.id} está em ${spec.phase}/ — só SPECs ativas são arquivadas (rascunho abandonado: discard)`);
  const mainPath = P(spec.dir, 'main.md');
  const pm = parseMain(read(mainPath));
  const pend = [];
  const crit = getCriteria(pm);
  if (!crit || !crit.length) pend.push('seção "## Critério de aceite" sem checkboxes — contrato R.6.2 vazio');
  else for (const c of crit) {
    if (!c.checked && !ACEITO_RE.test(c.raw)) {
      pend.push(`critério aberto sem marcador [aceito-incompleto: "citação literal do usuário" YYYY-MM-DD HH:MM]: "${truncate(c.text, 70)}" (R.6.2 — só o USUÁRIO aceita incompleto)`);
    }
    if (c.checked && !hasTs(c.raw)) pend.push(`checkbox [x] sem timestamp: "${truncate(c.text, 70)}" (R.6)`);
  }
  const dgp = P(spec.dir, 'digest.md');
  if (!exists(dgp)) pend.push('digest.md ausente — obrigatório no fechamento (≤2.000 bytes; ver docs/rules/lifecycle.md)');
  else {
    const db = digestMeasure(read(dgp));
    if (db > 2000) pend.push(`digest.md com ${db}B > 2000B (R.16) — re-gere dentro do cap: node scripts/specctl.mjs digest ${spec.id} --fix`);
  }
  const jp = P(spec.dir, 'journal.md');
  if (!exists(jp)) pend.push('journal.md ausente');
  else {
    const jtxt = read(jp);
    if (!/^## \d{4}-\d{2}-\d{2} \d{2}:\d{2} — (?:\[MARCO\] )?\[conclusão\]/m.test(jtxt)) pend.push('entrada [conclusão] ausente no LOG do journal');
    // SNAPSHOT ainda com placeholders do template = não reflete a conclusão (e o digest gerado herdaria o lixo)
    const snapEnd = jtxt.search(/^## LOG\b/m);
    const snap = snapEnd >= 0 ? jtxt.slice(0, snapEnd) : jtxt;
    if (SNAP_PLACEHOLDER.test(snap)) pend.push('SNAPSHOT ainda com placeholders do template ("Onde tô/Próximo passo/Fase" não preenchidos) — sobrescreva o SNAPSHOT do journal refletindo a conclusão antes de fechar');
  }
  if ((pm.fields['Commit final'] || '—').trim() === '—') pend.push('**Commit final:** não preenchido (R.6.1)');
  const feats = splitList(pm.fields.Features || '');
  if (!feats.length) pend.push('**Features:** vazio — R.4/R.7 exigem vínculo a feature');
  for (const f of feats) {
    const r = featureConcludedOk(root, f, spec.id);
    if (!r.ok) pend.push(r.why);
  }
  if (pend.length) {
    process.stderr.write(`archive BLOQUEADO — ${pend.length} pendência(s) em ${spec.id}:\n`);
    for (const p of pend) process.stderr.write(`  - ${p}\n`);
    process.exit(1);
  }
  archiveApply(root, spec);
  out(`arquivada: docs/archive/${spec.id} (claim removido, INDEX regenerado)`);
}

// cauda de fechamento (compartilhada por archive e close): estampa Status/Concluída,
// move p/ archive/ (ÚLTIMO ato mutador) e regenera índices (pós-move só index — idempotente)
function archiveApply(root, spec) {
  const mainPath = P(spec.dir, 'main.md');
  const pm = parseMain(read(mainPath));
  let txt = read(mainPath);
  txt = setField(txt, 'Status', 'done');
  if ((pm.fields['Concluída'] || '—') === '—') txt = setField(txt, 'Concluída', now());
  writeFile(mainPath, txt);
  const dst = moveSpec(spec, root, 'archive');
  removeClaim(root, spec.id);
  cmdIndex({ quiet: true });
  return dst;
}

function cmdDiscard(pos, flags) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  if (spec.phase !== 'active' && spec.phase !== 'future') die(`discard: ${spec.id} está em ${spec.phase}/ — nada a descartar`);
  const motivo = flags.motivo;
  if (!motivo) die('discard exige --motivo "..." (R.5: descarte preserva aprendizado com justificativa)');
  const mainPath = P(spec.dir, 'main.md');
  let txt = read(mainPath);
  if (!txt.includes('## Justificativa de descarte')) {
    if (!txt.endsWith('\n')) txt += '\n';
    txt += `\n## Justificativa de descarte\n\n${motivo} (${now()})\n`;
  }
  txt = setField(txt, 'Status', 'discarded');
  writeFile(mainPath, txt);
  appendLog(spec.dir, 'conclusão', `Descartada: ${motivo}`);
  // digest gerado AUTOMÁTICO (paridade com o close — nunca conte bytes à mão); refine depois via digest <id> --stdin
  const dgPath = P(spec.dir, 'digest.md');
  let dgNote = 'digest preservado';
  if (!exists(dgPath) || digestMeasure(read(dgPath)) > 2000) {
    writeFile(dgPath, genDigest(root, spec, { concluida: now() }));
    dgNote = `digest gerado (${digestMeasure(read(dgPath))}B)`;
  }
  moveSpec(spec, root, 'discard');
  removeClaim(root, spec.id);
  cmdIndex({ quiet: true });
  out(`descartada: docs/discard/${spec.id} (justificativa + ${dgNote}, INDEX regenerado)`);
  out(`lições/gotchas: refine o digest se preciso — node scripts/specctl.mjs digest ${spec.id} --stdin`);
}

// ---------------------------------------------------------------- features / taxonomy / index

function featureFiles(root) {
  const base = P(root, 'docs', 'features');
  return walkFiles(base, { exts: ['.md'] })
    .filter((f) => !f.endsWith('.history.md'))
    .map((f) => ({ path: f, area: relOf(base, f).replace(/\.md$/, '') }));
}
function parseFeature(txt) {
  const t = norm(txt);
  const lines = t.split('\n');
  const kw = (/^\*\*Keywords:\*\*\s*(.*)$/m.exec(t) || [])[1] || '';
  const resumo = (/^\*\*Resumo:\*\*\s*(.*)$/m.exec(t) || [])[1] || '';
  const paths = [];
  const ai = lines.findIndex((l) => /^\*\*Arquivos principais:\*\*/.test(l));
  if (ai >= 0) {
    for (let i = ai + 1; i < lines.length; i++) {
      const m = /^\s+-\s+(.+)$/.exec(lines[i]) || /^-\s+(.+)$/.exec(lines[i]);
      if (m) paths.push(m[1].trim().replace(/^`|`$/g, ''));
      else break;
    }
  }
  return { kw, resumo, paths };
}
function parseTaxonomy(root) {
  const p = P(root, 'docs', 'TAXONOMY.md');
  if (!exists(p)) return null;
  const set = new Set();
  // comentários HTML (exemplos dos stubs) e fenced code NÃO entram no vocabulário
  for (const m of stripFences(norm(read(p))).matchAll(/^-\s+(\S+)\s+—/gm)) set.add(m[1]);
  return set;
}
const cleanCell = (s) => (s || '').replace(/\|/g, '/').trim() || '—';

function genIndex(root) {
  const feats = featureFiles(root)
    .map((f) => ({ area: f.area, ...parseFeature(readSafe(f.path)) }))
    .sort((a, b) => (a.area < b.area ? -1 : 1));
  let s = `# INDEX\n\n${GERADO_MARK}\n\n`;
  if (!feats.length) return s + '_Sem features ainda._\n';
  const groups = new Map();
  for (const f of feats) {
    const ns = f.area.includes('/') ? f.area.split('/')[0] : 'geral';
    if (!groups.has(ns)) groups.set(ns, []);
    groups.get(ns).push(f);
  }
  for (const ns of [...groups.keys()].sort()) {
    s += `## ${ns}\n\n`;
    for (const f of groups.get(ns)) {
      // INDEX é mapa de roteamento (nome → keywords → feature); resumo/paths vivem na feature.
      const kw = (f.kw || '').split(',').slice(0, 6).join(',').trim() || '(sem keywords)';
      s += `- **${f.area}** — ${truncate(kw, 90)}\n`;
    }
    s += '\n';
  }
  return s.replace(/\n+$/, '\n');
}
function genArchiveIndex(root) {
  const rows = [];
  for (const spec of listSpecs(root).filter((x) => x.phase === 'archive' || x.phase === 'discard').sort((a, b) => (a.id < b.id ? -1 : 1))) {
    const pm = parseMain(readSafe(P(spec.dir, 'main.md')));
    const status = pm.fields.Status || (spec.phase === 'archive' ? 'done' : 'discarded');
    rows.push(`${spec.id} | ${cleanCell(status)} | ${cleanCell(pm.fields.Features)} | ${cleanCell(pm.fields.Keywords)} | ${cleanCell(pm.fields.Resumo)}`);
  }
  let s = `# ARCHIVE-INDEX\n\n${GERADO_MARK}\n\n`;
  s += rows.length ? rows.join('\n') + '\n' : '_Vazio._\n';
  return s;
}
// DEFERRED: índice vivo do que foi deixado para depois COM autorização (R.6.2) — os marcadores
// [aceito-incompleto] ficam espalhados nos mains (inclusive arquivados, que o guard N3 protege);
// este índice gerado os torna visíveis sem abrir archive. Deferral sem citação não existe (R.6.2).
function genDeferred(root) {
  const rows = [];
  const CITE_RE = /\[aceito-incompleto:\s*"([^"]+)"\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]/;
  for (const spec of listSpecs(root).sort((a, b) => (a.id < b.id ? -1 : 1))) {
    const pm = parseMain(readSafe(P(spec.dir, 'main.md')));
    for (const c of getCriteria(pm) || []) {
      const m = CITE_RE.exec(c.raw);
      if (!m) continue;
      const critTxt = c.text.replace(CITE_RE, '').replace(/\s*\|\s*verify:.*$/, '').trim();
      rows.push(`- ${spec.id} (${spec.phase}) | ${cleanCell(truncate(critTxt, 90))} | "${truncate(m[1], 70)}" ${m[2]}`);
    }
  }
  let s = `# DEFERRED — deixado para depois com autorização (R.6.2)\n\n${GERADO_MARK}\n\n`;
  s += rows.length
    ? `SPEC | critério deferido | citação do usuário:\n\n${rows.join('\n')}\n\nRetomar um item = SPEC nova citando a origem (ou reopen se o fechamento foi indevido).\n`
    : '_Nenhum item deferido — nenhum marcador [aceito-incompleto] no repositório._\n';
  return s;
}
function cmdIndex(opts = {}) {
  const root = requireRoot();
  ensureGitkeeps(root); // rede de segurança do CI: index roda no docs-gate e após close/archive — garante estrutura em checkout fresco
  writeFile(P(root, 'docs', 'INDEX.md'), genIndex(root));
  writeFile(P(root, 'docs', 'ARCHIVE-INDEX.md'), genArchiveIndex(root));
  writeFile(P(root, 'docs', 'PROGRAMS.md'), genProgramsIndex(root));
  writeFile(P(root, 'docs', 'DEFERRED.md'), genDeferred(root));
  if (!opts.quiet) out('regenerados: docs/INDEX.md, docs/ARCHIVE-INDEX.md, docs/PROGRAMS.md e docs/DEFERRED.md (determinístico, sem timestamp)');
}

// ---------------------------------------------------------------- descoberta de backlog (next/programs/roadmap)

// SPECs em future/ com Status draft (via main.md) — [{ id }]
function futureDraftSpecs(root) {
  const outArr = [];
  for (const s of listSpecs(root).filter((x) => x.phase === 'future')) {
    const st = parseMain(readSafe(P(s.dir, 'main.md'))).fields.Status || null;
    if (st === 'draft') outArr.push({ id: s.id, dir: s.dir });
  }
  return outArr.sort((a, b) => (a.id < b.id ? -1 : 1));
}
// lê docs/ROADMAP.md — array de SPEC-ids na ordem (ignora comentários/linhas sem SPEC-id)
function parseRoadmap(root) {
  const p = P(root, 'docs', 'ROADMAP.md');
  if (!exists(p)) return [];
  const ids = [];
  for (const line of stripFences(norm(read(p))).split('\n')) {
    // entradas "N. SPEC-..." ou "- SPEC-..." — extrai o SPEC-id por regex, linhas sem SPEC-id são ignoradas
    if (!/^\s*(?:\d+\.|-)\s+/.test(line)) continue;
    const m = /SPEC-\d{8}-\d{4}(?:-[a-z0-9][a-z0-9-]*)?/.exec(line);
    if (m) ids.push(m[0]);
  }
  return ids;
}
// estado derivado de um programa (status vem do main.md de cada nó, fonte única)
// retorna { ready:[], active:[], blocked:[{id,waits:[]}], done:[], total, open, owner }
function computeProgramState(prog, statusOf) {
  const ready = [], active = [], blocked = [], done = [], paused = [];
  const isDone = (st) => st === 'done' || st === 'discarded';
  for (const n of prog.nodes) {
    const st = statusOf(n.id);
    if (isDone(st)) { done.push(n.id); continue; }
    if (st === 'active') { active.push(n.id); continue; }
    if (st === 'paused') { paused.push(n.id); continue; } // visível, mas não pegável — retomar é decisão (resume)
    if (st === 'draft') {
      const waits = n.deps.filter((d) => !isDone(statusOf(d)));
      if (waits.length) blocked.push({ id: n.id, waits });
      else ready.push(n.id);
    }
    // null (nó sem SPEC): o audit --deps acusa como erro — aqui não listado
  }
  const total = prog.nodes.length;
  const open = done.length < total; // ≥1 nó ∉ {done, discarded}
  return { ready, active, blocked, done, paused, total, open, owner: prog.owner || '—' };
}
// conteúdo determinístico de docs/PROGRAMS.md (GERADO por specctl index) — formato §1 do contrato
function genProgramsIndex(root) {
  const statusOf = makeStatusOf(listSpecs(root));
  const progs = parsePrograms(root);
  let s = `# PROGRAMS\n\n${GERADO_MARK}\n\n`;
  if (!progs.length) return s + '_Sem programas._\n';
  const entries = progs.map((p) => ({ prog: p, state: computeProgramState(p, statusOf) }));
  // ordenar: abertos primeiro, depois concluídos; dentro, por slug
  entries.sort((a, b) => {
    if (a.state.open !== b.state.open) return a.state.open ? -1 : 1;
    return a.prog.slug < b.prog.slug ? -1 : 1;
  });
  const blocks = [];
  for (const { prog, state } of entries) {
    const situacao = state.open ? 'aberto' : 'concluído';
    let block = `## ${prog.slug} — ${situacao} · ${state.done.length}/${state.total} · owner ${state.owner}\n`;
    if (state.ready.length) block += `- prontos: ${state.ready.join(', ')}\n`;
    if (state.active.length) block += `- em progresso: ${state.active.join(', ')}\n`;
    if (state.blocked.length) {
      const bl = state.blocked.map((b) => `${b.id} (aguarda ${b.waits.join(', ')})`).join(', ');
      block += `- bloqueados: ${bl}\n`;
    }
    if (state.paused.length) block += `- pausados: ${state.paused.join(', ')} (retomar: specctl resume)\n`;
    if (state.done.length) block += `- concluídos: ${state.done.join(', ')}\n`;
    blocks.push(block);
  }
  return s + blocks.join('\n');
}

// ---------------------------------------------------------------- lint (§8)

function extractRfs(txt) {
  const clean = stripFences(norm(txt)); // RF-n de EXEMPLO em bloco de código não é requisito real
  const s = new Set();
  for (const m of clean.matchAll(/^\s*(?:#{1,6}\s+|[-*]\s+|\d+\.\s+)?\*{0,2}RF-(\d+)/gm)) s.add(+m[1]);
  if (!s.size) for (const m of clean.matchAll(/\bRF-(\d+)\b/g)) s.add(+m[1]);
  return s;
}
function coveredRfs(text) {
  const s = new Set();
  for (const m of text.matchAll(/\(cobre ([^)]*)\)/g)) {
    for (const r of m[1].matchAll(/RF-(\d+)/g)) s.add(+r[1]);
  }
  return s;
}
function lintJournal(root, jp, err, warn2, v3) {
  const rep = (r, m) => { if (v3 && warn2) warn2(r, m, { stage1: true }); else err(r, m); };
  const txt = norm(read(jp));
  const lines = txt.split('\n');
  const relp = relOf(root, jp);
  const snapIdx = [];
  lines.forEach((l, i) => { if (/^## SNAPSHOT\b/.test(l)) snapIdx.push(i); });
  if (!snapIdx.length) err(relp, 'journal sem heading "## SNAPSHOT" (formato §3.3)');
  else {
    if (snapIdx[0] >= 60) err(relp, `SNAPSHOT começa na linha ${snapIdx[0] + 1} — DEVE caber nas primeiras 60 linhas`);
    if (snapIdx.length > 1) err(relp, 'heading "## SNAPSHOT" duplicado — SNAPSHOT é único e sobrescrito');
  }
  const logIdx = lines.findIndex((l) => /^## LOG\b/.test(l));
  if (logIdx >= 0 && snapIdx.length && logIdx > 60) err(relp, `SNAPSHOT termina na linha ${logIdx + 1} — DEVE caber nas primeiras 60 linhas (o brief trunca em 60)`);
  const snapStart = snapIdx.length ? snapIdx[0] : -1;
  const snapEnd = logIdx >= 0 ? logIdx : lines.length;
  lines.forEach((l, i) => {
    if ((/^#{1,6}\s.*TL;?DR/i.test(l) || /^\*\*TL;?DR/i.test(l)) && (i < snapStart || i >= snapEnd)) {
      err(relp, `TL;DR fora do SNAPSHOT (linha ${i + 1}) — o único sumário sobrescrito é o SNAPSHOT`);
    }
  });
  if (logIdx >= 0) {
    const entryRe = new RegExp(`^## \\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2} — \\[(MARCO|${LOG_TYPES.join('|')})\\]`);
    for (let i = logIdx + 1; i < lines.length; i++) {
      if (/^##\s/.test(lines[i]) && !entryRe.test(lines[i])) {
        rep(relp, `entrada de LOG inválida (linha ${i + 1}): "${truncate(lines[i], 60)}" — formato: ## YYYY-MM-DD HH:MM — [tipo] Título; tipos: ${LOG_TYPES.join(' ')}`);
      }
    }
  }
}
const POINTER_KEYS = ['PRD', 'TechSpec', 'Tasks', 'QA', 'Review', 'Bugfix', 'Bugs', 'Evidence'];

function runLint(root, opts = {}) {
  const E = [], W = [];
  const err = (f, m) => E.push({ f, m });
  // stage1: avisos "warn no 1º release" (§8) — NUNCA promovidos a erro por --strict
  const warn = (f, m, o = {}) => W.push({ f, m, ...o });

  // manifesto
  const manPath = P(root, 'docs', '.spec-system.json');
  if (!exists(manPath)) warn('docs/.spec-system.json', 'manifesto ausente — modo compatibilidade v3 (rode a skill spec-system-init, modo UPGRADE)');
  else { try { JSON.parse(read(manPath)); } catch (e) { err('docs/.spec-system.json', `JSON inválido: ${e.message}`); } }

  // estrutura de pastas
  for (const d of ['features', 'active', 'future', 'archive', 'discard', 'claims', 'programs']) {
    if (!isDir(P(root, 'docs', d))) err(`docs/${d}/`, 'pasta obrigatória ausente (estrutura v4 — rode specctl init)');
  }

  // taxonomy + features
  const tax = parseTaxonomy(root);
  const feats = featureFiles(root);
  if (!tax && feats.length) warn('docs/TAXONOMY.md', 'ausente — R.13 exige vocabulário canônico de áreas');
  const decSeen = new Map();
  for (const f of feats) {
    const relp = relOf(root, f.path);
    const txt = norm(readSafe(f.path));
    if (!/^\*\*Keywords:\*\*/m.test(txt)) err(relp, 'feature sem linha **Keywords:** (formato §4)');
    if (!/^\*\*Resumo:\*\*/m.test(txt)) err(relp, 'feature sem linha **Resumo:** (formato §4)');
    for (const h of ['## Specs desta feature', '## Estado atual', '## Decisões arquiteturais ativas', '## Gotchas']) {
      if (!txt.includes(h)) err(relp, `seção obrigatória ausente: "${h}" (formato §4)`);
    }
    if (/###\s+Em execução/.test(txt)) warn(relp, 'seção "Em execução" foi removida na v4 — o trabalho em voo vive em docs/claims/ (specctl activate)');
    for (const m of stripFences(txt).matchAll(/^\s*-\s*(?:\*\*)?(DEC-\d{8}-\d{4}(?:-[a-z0-9-]+)?)/gm)) { // DEC de EXEMPLO em fence não conta
      if (decSeen.has(m[1])) err(relp, `DEC-id duplicado: ${m[1]} (também definido em ${decSeen.get(m[1])})`);
      else decSeen.set(m[1], relp);
    }
    // features/<area>.md NÃO tem teto: é memória viva por área, auto-carregada no N1, e o nº de features do sistema é ilimitado. Rollup (specctl rollup <area>) é ferramenta MANUAL, opcional — o autor decide quando enxugar o auto-load; nada é lintado nem bloqueado por tamanho de feature.
    if (tax && !tax.has(f.area)) err(relp, `feature '${f.area}' não coberta pela TAXONOMY.md — R.13: adicione a linha '- ${f.area} — <definição>'`);
  }

  // SPECs
  for (const spec of listSpecs(root)) {
    const relDir = `docs/${spec.phase}/${spec.id}`;
    if (!SPEC_RE.test(spec.id)) { err(relDir, 'nome de pasta fora do padrão SPEC-YYYYMMDD-HHMM-slug (R.1)'); continue; }
    const mainPath = P(spec.dir, 'main.md');
    const mainRel = `${relDir}/main.md`;
    if (!exists(mainPath)) { err(relDir, 'main.md ausente (arquivo canônico — R.3)'); continue; }
    const pm = parseMain(read(mainPath));
    for (const k of ['Status', 'Porte', 'Owner', 'Criada', 'Keywords', 'Features', 'Resumo']) {
      if (!(k in pm.fields) || pm.fields[k] === '') err(mainRel, `campo obrigatório ausente/vazio: **${k}:** (formato §3.1)`);
    }
    const st = pm.fields.Status;
    if (st && !STATUS_ENUM.includes(st)) err(mainRel, `Status inválido '${st}' — enum: ${STATUS_ENUM.join(' | ')}`);
    if (pm.fields.Porte && !['P', 'M', 'G'].includes(pm.fields.Porte)) err(mainRel, `Porte inválido '${pm.fields.Porte}' — use P | M | G`);
    if (pm.fields.Owner === '—') err(mainRel, 'Owner obrigatório (use @handle) — formato §3.1');
    if (st && STATUS_ENUM.includes(st) && !PHASE_STATUS[spec.phase].includes(st)) {
      err(mainRel, `coerência pasta↔status violada: ${spec.phase}/ exige status ${PHASE_STATUS[spec.phase].join(' ou ')}, encontrado '${st}'`);
    }
    const tm = /^# SPEC-(\d{8}-\d{4})\b/.exec(pm.lines[0] || '');
    if (!tm) warn(mainRel, 'título fora do formato "# SPEC-YYYYMMDD-HHMM: <Título>"');
    else if (`SPEC-${tm[1]}` !== idPrefix(spec.id)) warn(mainRel, `título (${tm[1]}) não bate com o id da pasta (${spec.id})`);
    for (const t of ['Objetivo', 'Implementação']) {
      if (!sectionRange(pm, (x) => x === t || x.startsWith(t + ' '))) err(mainRel, `seção obrigatória ausente: ## ${t}`);
    }
    const esc = sectionRange(pm, (x) => x === 'Escopo' || x.startsWith('Escopo'));
    if (!esc) err(mainRel, 'seção obrigatória ausente: ## Escopo (DENTRO/FORA)');
    else {
      const body = pm.lines.slice(esc[0], esc[1]).join('\n');
      if (!body.includes('DENTRO') || !body.includes('FORA')) warn(mainRel, 'seção Escopo sem blocos DENTRO/FORA explícitos');
    }
    const specFeats = splitList(pm.fields.Features || '');
    if (tax) {
      for (const ft of specFeats) {
        if (!tax.has(ft)) err(mainRel, `feature '${ft}' não existe na TAXONOMY.md (R.4/R.13)`);
      }
    } else if (specFeats.length) {
      warn(mainRel, 'docs/TAXONOMY.md ausente — vínculo **Features:** não validável (R.4); crie a TAXONOMY');
    }
    if (!specFeats.length && st && st !== 'draft') warn(mainRel, '**Features:** vazio — R.4 exige vínculo a feature antes da ativação');
    // checkboxes do main.md (qualquer [x] sem timestamp = ERRO — R.6)
    pm.lines.forEach((l) => {
      const m = /^\s*-\s*\[(x|X)\]\s*(.*)$/.exec(l);
      if (m && !hasTs(l)) { const msg = `checkbox [x] sem timestamp (R.6): "${truncate(m[2], 60)}"`; if (spec.v3) warn(mainRel, msg, { stage1: true }); else err(mainRel, msg); }
    });
    const crit = getCriteria(pm);
    const porteLint = (pm.fields.Porte || 'M').toUpperCase();
    if (crit === null) err(mainRel, 'seção obrigatória ausente: ## Critério de aceite');
    else {
      if (!crit.length) warn(mainRel, 'Critério de aceite sem checkboxes — o contrato R.6.2 está vazio');
      // D1 — gramática por porte: P não usa verify: (evidência via check); M/G mantêm verify:
      // Só vale para SPECs em construção (active/future); archive/discard são históricas e imutáveis
      // (SPECs P v4.0 com verify: foram legais quando fechadas — não reprovar retroativamente). v3-compat idem.
      if (porteLint === 'P' && (spec.phase === 'active' || spec.phase === 'future') && !spec.v3) {
        for (const c of crit) {
          if (hasVerifyTag(c.raw)) err(mainRel, `porte P não usa verify: — use specctl check (ou escalate para M): "${truncate(c.text, 60)}"`);
        }
      }
      for (const c of crit) {
        if (c.checked) {
          const evid = (hasTs(c.raw) && hasCommitEv(c.raw)) || hasVerifyTag(c.raw) || hasEvidenceTag(c.raw);
          if (!evid) {
            const msg = `critério [x] sem evidência (timestamp+commit, verify: ou evidence:): "${truncate(c.text, 60)}" (R.6.2)`;
            if (spec.phase === 'archive' && !spec.v3) err(mainRel, msg); else warn(mainRel, msg, { stage1: true });
          }
        } else if (spec.phase === 'archive') {
          const critErr = spec.v3 ? (mm) => warn(mainRel, mm, { stage1: true }) : (mm) => err(mainRel, mm);
          if (!c.raw.includes('[aceito-incompleto')) critErr(`critério aberto em archive sem marcador [aceito-incompleto: "citação" YYYY-MM-DD HH:MM]: "${truncate(c.text, 60)}" (R.6.2 — só o USUÁRIO aceita incompleto)`);
          else if (!ACEITO_RE.test(c.raw)) critErr(`marcador [aceito-incompleto: ...] malformado — exige citação entre aspas + timestamp: "${truncate(c.text, 60)}"`);
        }
      }
    }
    if (spec.phase === 'archive' && (pm.fields['Commit final'] || '—').trim() === '—') {
      err(mainRel, '**Commit final:** — em SPEC arquivada (R.6.1: registre o hash final)');
    }
    if (spec.phase === 'archive' || spec.phase === 'discard') {
      const dg = P(spec.dir, 'digest.md');
      if (!exists(dg)) err(`${relDir}/digest.md`, 'digest.md obrigatório no fechamento (archive E discard) — ≤2.000 bytes');
      else {
        const b = digestMeasure(read(dg)); // 2c: LF + comentários HTML descontados
        if (b > 2000) err(`${relDir}/digest.md`, `orçamento excedido: ${b} > 2000 bytes (R.16) — digest é o resumo denso, não o journal`);
      }
    }
    if (spec.phase === 'discard' && !pm.raw.includes('## Justificativa de descarte')) {
      err(mainRel, 'SPEC descartada sem seção "## Justificativa de descarte" (R.5)');
    }
    const jp = P(spec.dir, 'journal.md');
    const needJournal = spec.phase === 'active' || spec.phase === 'archive' || spec.phase === 'discard' || (spec.phase === 'future' && st === 'paused');
    if (needJournal && !exists(jp)) err(`${relDir}/journal.md`, 'journal.md ausente (arquivo canônico — R.3; pausada mantém main+journal)');
    if (exists(jp)) lintJournal(root, jp, err, warn, spec.v3);
    for (const key of POINTER_KEYS) {
      const v = pm.fields[key];
      if (!v || v === '—') continue;
      const target = v.split(/\s+\(/)[0].trim().replace(/^`|`$/g, '');
      if (!target) continue;
      if (!exists(P(spec.dir, target)) && !exists(P(root, target))) {
        warn(mainRel, `ponteiro **${key}:** aponta para arquivo inexistente: ${target}`, { stage1: true });
      }
    }
    const ws = pm.fields.Workspace;
    if (ws && ws !== '—' && ws !== 'inline' && !exists(P(root, ws)) && spec.phase === 'active') {
      warn(mainRel, `**Workspace:** '${ws}' não existe no repositório`);
    }
    const prdPath = P(spec.dir, 'prd.md');
    if (exists(prdPath) && crit) {
      const rfs = extractRfs(read(prdPath));
      const covered = coveredRfs(crit.map((c) => c.raw).join('\n'));
      for (const n of [...rfs].sort((a, b) => a - b)) {
        if (!covered.has(n)) err(mainRel, `RF-${n} do prd.md sem cobertura no Critério de aceite — use "(cobre RF-${n})" em ≥1 critério (rastreabilidade §3.2)`);
      }
    }
  }

  // orçamentos de camada (R.16)
  // AGENTS.md carrega, por necessidade, a seção "Sem hooks?" que o CLAUDE.md dispensa (hooks fazem esse trabalho) — orçamento diferenciado, não hack.
  // docs/INDEX.md NÃO entra: é enumeração GERADA (specctl index) cujo tamanho escala com features×SPECs — capar em bytes é erro de categoria (deadlock: gerado não se edita). Disciplina do INDEX é por-entrada (1 linha/SPEC), não por total.
  for (const [f, max] of [['CLAUDE.md', 6000], ['AGENTS.md', 6200], ['docs/RULES.md', 5000]]) {
    const fp = P(root, ...f.split('/'));
    if (exists(fp)) {
      const b = lfBytes(read(fp)); // 2c: bytes LF-normalizados (strip CR/BOM)
      if (b > max) E.push({ f, m: `orçamento excedido: ${b} > ${max} bytes (R.16) — mova conteúdo para camada mais profunda (rollup, não corte)` });
    }
  }

  // ROADMAP: entrada morta some da descoberta em silêncio — id com typo/arquivado/descartado é invisível no `next`
  {
    const allSpecs = listSpecs(root);
    const phaseOf = new Map(allSpecs.map((s) => [s.id, s.phase]));
    const statusOf = makeStatusOf(allSpecs);
    for (const id of parseRoadmap(root)) {
      if (!phaseOf.has(id)) { warn('docs/ROADMAP.md', `cita ${id} que NÃO EXISTE (typo?) — a entrada é ignorada pelo specctl next`); continue; }
      const ph = phaseOf.get(id), st = statusOf(id);
      if (ph === 'archive' || ph === 'discard') warn('docs/ROADMAP.md', `cita ${id} já em ${ph}/ — remova a linha (entrada morta, ignorada pelo next)`);
      else if (ph === 'future' && st === 'paused') warn('docs/ROADMAP.md', `cita ${id} PAUSADA — retome via specctl resume ou remova do roadmap (paused não aparece no next)`);
    }
  }
  // INDEX/ARCHIVE-INDEX/DEFERRED gerados e idempotentes (DEFERRED só warn quando ausente — repos v4.0/4.1 antigos não têm)
  for (const [f, gen] of [['docs/INDEX.md', genIndex], ['docs/ARCHIVE-INDEX.md', genArchiveIndex], ['docs/DEFERRED.md', genDeferred]]) {
    const fp = P(root, ...f.split('/'));
    if (!exists(fp)) { W.push({ f, m: 'ausente — rode: node scripts/specctl.mjs index' }); continue; }
    const txt = read(fp);
    if (!txt.includes(GERADO_MARK)) E.push({ f, m: `marcador "${GERADO_MARK}" ausente — arquivo é GERADO, não edite à mão` });
    else if (norm(gen(root)) !== norm(txt)) E.push({ f, m: 'desatualizado (regeneração difere) — rode: node scripts/specctl.mjs index' });
  }

  // secret-scan em docs/ (R.15) — ERRO
  for (const fp of walkFiles(P(root, 'docs'), { exts: ['.md', '.txt', '.json', '.yml', '.yaml'] })) {
    for (const h of scanSecrets(readSafe(fp))) {
      E.push({ f: relOf(root, fp), m: `segredo detectado (${h.tipo}) na linha ${h.line} — R.15: substitua por <REDACTED:${h.tipo}> e ROTACIONE a credencial` });
    }
  }

  if (opts.targetMain) {
    const act = activeSpecs(root);
    if (act.length) E.push({ f: 'docs/active/', m: `R.2: docs/active/ deve estar vazio em main — encontrado: ${act.map((s) => s.id).join(', ')}` });
  }
  return { E, W };
}
function reportLint(E, W) {
  // tom (2b): erros primeiro; avisos DEPOIS, sob header que deixa claro que não bloqueiam
  for (const e of E) process.stderr.write(`ERRO  ${e.f}: ${e.m}\n`);
  if (W.length) {
    process.stdout.write('AVISOS (não bloqueiam archive/close/CI):\n');
    for (const w of W) process.stdout.write(`AVISO ${w.f}: ${w.m}\n`);
  }
  process.stdout.write(`\nlint: ${E.length} erro(s), ${W.length} aviso(s)\n`);
}
function cmdLint(flags) {
  const root = requireRoot();
  const { E, W } = runLint(root, { targetMain: !!flags['target-main'] });
  reportLint(E, W);
  // --strict promove a erro APENAS avisos não-stage1 (§8: ponteiro ausente e [x] sem evidência em active/ ficam warn no 1º release; tamanho de feature não é mais lintado)
  const strictW = W.filter((w) => !w.stage1);
  const fail = E.length > 0 || (flags.strict && strictW.length > 0);
  if (flags.strict && !E.length && strictW.length) process.stdout.write('(--strict: avisos contam como falha — exceto avisos de 1º release do §8)\n');
  process.exit(fail ? 1 : 0);
}

// ---------------------------------------------------------------- audit (§8)

function parsePrograms(root) {
  const progs = [];
  const base = P(root, 'docs', 'programs');
  if (!isDir(base)) return progs;
  for (const fp of walkFiles(base, { exts: ['.md'] })) {
    const txt = norm(readSafe(fp));
    const nodes = [];
    for (const m of txt.matchAll(/^-\s+(SPEC-\S+)\s*\|\s*depende de:\s*(.*)$/gm)) {
      const deps = m[2].trim() === '—' ? [] : [...m[2].matchAll(/SPEC-[\w-]+/g)].map((x) => x[0]);
      nodes.push({ id: m[1], deps });
    }
    // Owner declarado no manifesto do programa (**Owner:** @handle)
    const owner = ((/^\*\*Owner:\*\*\s*(.*)$/m.exec(txt) || [])[1] || '').trim() || '—';
    progs.push({ slug: path.basename(fp, '.md'), rel: relOf(root, fp), txt, nodes, owner });
  }
  return progs;
}
// resolve o Status (main.md) de um SPEC-ref (id exato, prefixo ou prefixo de timestamp) — null se não existe
function makeStatusOf(specs) {
  return (ref) => {
    // igualdade exata em TODA a lista PRIMEIRO — fallback por prefixo só depois (duas SPECs no mesmo
    // minuto compartilham o idPrefix; o .find() com OR devolvia o status da vizinha e corrompia o DAG)
    let s = specs.find((x) => x.id === ref);
    if (!s) s = specs.find((x) => x.id.startsWith(ref) || ref.startsWith(idPrefix(x.id)));
    if (!s) return null;
    return parseMain(readSafe(P(s.dir, 'main.md'))).fields.Status || null;
  };
}
function auditDeps(root, E, W) {
  const specs = listSpecs(root);
  const statusOf = makeStatusOf(specs);
  for (const prog of parsePrograms(root)) {
    if (!prog.nodes.length) { W.push({ f: prog.rel, m: 'programa sem nós (- SPEC-<id> | depende de: ...)' }); continue; }
    if (/^\s*(\*\*)?Bloqueia/m.test(prog.txt)) W.push({ f: prog.rel, m: '"Bloqueia"/ordem são DERIVADOS do DAG — não escreva no manifesto (R.14)' });
    const known = new Map(prog.nodes.map((n) => [n.id, n]));
    for (const n of prog.nodes) {
      if (statusOf(n.id) === null) E.push({ f: prog.rel, m: `nó inexistente no repositório: ${n.id} (R.14: todo nó do programa é uma SPEC real)` });
      for (const d of n.deps) {
        if (statusOf(d) === null && !known.has(d)) E.push({ f: prog.rel, m: `dependência inexistente: ${n.id} depende de ${d}` });
      }
    }
    // ciclos (DFS)
    const color = new Map();
    const stack = [];
    let cycle = null;
    const visit = (id) => {
      if (cycle) return;
      color.set(id, 1); stack.push(id);
      for (const d of (known.get(id)?.deps || [])) {
        if (!known.has(d)) continue;
        if (color.get(d) === 1) { cycle = [...stack.slice(stack.indexOf(d)), d]; return; }
        if (!color.has(d)) visit(d);
      }
      color.set(id, 2); stack.pop();
    };
    for (const n of prog.nodes) { if (!color.has(n.id)) visit(n.id); if (cycle) break; }
    if (cycle) E.push({ f: prog.rel, m: `ciclo de dependências detectado: ${cycle.join(' → ')} (R.14: DAG obrigatório)` });
    // coerência status × DAG
    for (const n of prog.nodes) {
      const st = statusOf(n.id);
      for (const d of n.deps) {
        const ds = statusOf(d);
        if (st === 'done' && ds && ds !== 'done') W.push({ f: prog.rel, m: `incoerência status×DAG: ${n.id} (done) depende de ${d} (${ds})` });
        if (st === 'active' && ds === 'discarded') W.push({ f: prog.rel, m: `incoerência status×DAG: ${n.id} (active) depende de ${d} (discarded)` });
      }
    }
  }
}
const PIPELINE_ART_RE = /^docs\/(active|future|archive|discard)\/(SPEC-[^/]+)\/((?:\d+_task(?:_review)?|tasks|prd|techspec|bugs|qa-report|review-report|bugfix-report)\.md)$/;

function auditPr(root, base, E, W) {
  if (!base) die('audit --pr exige --base <sha> (base do PR) — sem base resolvível o gate falha FECHADO');
  git(['rev-parse', '--verify', `${base}^{commit}`], root);
  const diff = git(['diff', '--name-status', '-M', `${base}...HEAD`], root);
  const removedActive = new Set();
  const touched = new Set();
  const added = new Set();
  const specIdFrom = (p) => {
    const m = /^docs\/active\/(SPEC-[^/]+)\//.exec(p);
    return m ? m[1] : null;
  };
  for (const line of diff.split('\n').filter(Boolean)) {
    const parts = line.split('\t');
    const st = parts[0];
    if (st.startsWith('R')) {
      const [, oldP, newP] = parts;
      touched.add(newP); added.add(newP);
      const sid = specIdFrom(oldP);
      if (sid && !newP.startsWith(`docs/active/${sid}/`)) removedActive.add(sid);
    } else {
      const p = parts[1];
      touched.add(p);
      if (st === 'A') added.add(p);
      if (st === 'D') { const sid = specIdFrom(p); if (sid) removedActive.add(sid); }
    }
  }
  const specs = listSpecs(root);
  for (const id of removedActive) {
    const loc = specs.find((s) => s.id === id);
    if (loc && loc.phase === 'active') continue; // reorganização interna, segue ativa
    if (!loc) { E.push({ f: `docs/active/${id}`, m: 'SPEC saiu de docs/active/ e NÃO existe mais no repositório — R.5: nunca deletar; destinos válidos: archive/ (done), discard/ (com justificativa) ou future/ (pausada)' }); continue; }
    const pm = parseMain(readSafe(P(loc.dir, 'main.md')));
    const relMain = `docs/${loc.phase}/${id}/main.md`;
    if (loc.phase === 'archive') {
      if (!exists(P(loc.dir, 'digest.md'))) E.push({ f: relMain, m: 'archive sem digest.md — bloqueado (fechamento §3.4)' });
      const crit = getCriteria(pm) || [];
      for (const c of crit) {
        if (!c.checked && !ACEITO_RE.test(c.raw)) E.push({ f: relMain, m: `archive com critério aberto sem [aceito-incompleto: ...]: "${truncate(c.text, 60)}" (R.6.2)` });
        if (c.checked && !((hasTs(c.raw) && hasCommitEv(c.raw)) || hasVerifyTag(c.raw) || hasEvidenceTag(c.raw))) E.push({ f: relMain, m: `archive com critério [x] sem evidência: "${truncate(c.text, 60)}" (R.6.2)` });
      }
      for (const ft of splitList(pm.fields.Features || '')) {
        const r = featureConcludedOk(root, ft, id);
        if (!r.ok) E.push({ f: relMain, m: r.why + ' — R.7 valida por CONTEÚDO no diff do PR' });
      }
    } else if (loc.phase === 'discard') {
      if (!pm.raw.includes('## Justificativa de descarte')) E.push({ f: relMain, m: 'discard sem seção "## Justificativa de descarte" — bloqueado (R.5)' });
      if (!exists(P(loc.dir, 'digest.md'))) E.push({ f: relMain, m: 'discard sem digest.md — bloqueado (lições preservadas, R.5)' });
    } else if (loc.phase === 'future') {
      if ((pm.fields['Pausada em'] || '—').trim() === '—') E.push({ f: relMain, m: 'SPEC voltou a future/ sem **Pausada em:** preenchido — pausa legítima registra motivo (R.5)' });
    }
  }
  for (const p of added) {
    const m = PIPELINE_ART_RE.exec(p);
    if (!m) continue;
    const sid = m[2];
    const journalTouched = [...touched].some((t) => t.endsWith('/journal.md') && t.includes(`/${sid}/`));
    if (!journalTouched) W.push({ f: p, m: `artefato de pipeline sem contrapartida no journal da ${sid} (R.6.1) — registre [nota]/[decisão]/[descoberta] no LOG` });
  }
  // arquivo no commit base (ausência = condição esperada de PR, não erro): retorna null sem AVISO
  const showAtBase = (relPath) => { const r = gitRun(['show', `${base}:${relPath}`], root); return r.ok ? r.out : null; };
  // (4c-i) campo Porte mudou base..HEAD sem entrada de journal (escalate/deescalate/porte) = ERRO (D2)
  for (const s of specs.filter((x) => x.phase === 'active')) {
    const relMain = `docs/active/${s.id}/main.md`;
    const baseMain = showAtBase(relMain);
    if (baseMain == null) continue; // main.md não existia no base (SPEC nova/movida) — nada a diffar
    const basePorte = (parseMain(baseMain).fields.Porte || '').toUpperCase();
    const headPorte = (parseMain(readSafe(P(s.dir, 'main.md'))).fields.Porte || '').toUpperCase();
    if (basePorte && headPorte && basePorte !== headPorte) {
      const jTxt = norm(readSafe(P(s.dir, 'journal.md')));
      const logPart = jTxt.includes('## LOG') ? jTxt.slice(jTxt.indexOf('## LOG')) : jTxt;
      if (!/escalat|deescalat|porte/i.test(logPart)) {
        E.push({ f: relMain, m: `campo Porte mudou (${basePorte} → ${headPorte}) sem entrada de journal (escalate/deescalate) — use node scripts/specctl.mjs escalate|deescalate (D2), nunca edite **Porte:** à mão` });
      }
    }
  }
  // (features/<area>.md não têm ratchet de tamanho: crescer memória viva de uma área nunca bloqueia PR — rollup é manual/opcional.)
  // (4c-iii) R.17: commit do range que toca CÓDIGO sob SPEC ativa sem trailer `Spec: SPEC-<id>` = WARN
  // (warn, não erro: histórico não se reescreve barato — o aviso educa os próximos commits)
  if (specs.some((x) => x.phase === 'active')) {
    const lg = gitRun(['log', '--format=%h%x00%(trailers:key=Spec,valueonly,separator=%x2C)%x00%s', `${base}..HEAD`], root);
    if (lg.ok) {
      const missing = [];
      for (const row of lg.out.split('\n').filter(Boolean)) {
        const [h, trailers, subj] = row.split('\0');
        if (trailers && trailers.trim()) continue;
        const files = gitRun(['show', '--name-only', '--format=', h], root);
        if (!files.ok) continue;
        const touchesCode = files.out.split('\n').some((p) => p && !p.startsWith('docs/') && !p.startsWith('.scratch/') && !p.startsWith('.claude/') && !p.startsWith('.github/') && p !== 'scripts/specctl.mjs' && p !== 'CLAUDE.md' && p !== 'AGENTS.md');
        if (touchesCode) missing.push(`${h} "${truncate(subj || '', 50)}"`);
      }
      if (missing.length) W.push({ f: '(commits do PR)', m: `R.17: ${missing.length} commit(s) tocando código sob SPEC ativa SEM trailer 'Spec: SPEC-<id>': ${missing.slice(0, 3).join(' · ')}${missing.length > 3 ? ` (+${missing.length - 3})` : ''} — inclua o trailer nos próximos commits` });
    }
  }
}
function auditBase(root, E, W) {
  const specs = listSpecs(root);
  const ids = new Set(specs.map((s) => s.id));
  const prefixes = new Set(specs.map((s) => idPrefix(s.id)));
  // SPEC fantasma (fora de code fences)
  const seenGhost = new Set();
  for (const fp of walkFiles(P(root, 'docs'), { exts: ['.md'] })) {
    const txt = stripFences(readSafe(fp));
    for (const m of txt.matchAll(SPEC_REF_RE)) {
      const ref = m[0];
      if (ids.has(ref) || prefixes.has(ref)) continue;
      if ([...ids].some((i) => i.startsWith(ref))) continue;
      const key = `${relOf(root, fp)}|${ref}`;
      if (seenGhost.has(key)) continue;
      seenGhost.add(key);
      W.push({ f: relOf(root, fp), m: `referência a SPEC fantasma: ${ref} (não existe em nenhuma fase)` });
    }
  }
  // staleness por CONTEÚDO (nunca mtime)
  const DAY = 24 * 3600 * 1000;
  for (const s of specs.filter((x) => x.phase === 'active')) {
    const jp = P(s.dir, 'journal.md');
    if (!exists(jp)) continue;
    const m = /^\*\*Última atualização:\*\*\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})/m.exec(readSafe(jp));
    if (!m) { W.push({ f: `docs/active/${s.id}/journal.md`, m: 'SNAPSHOT sem **Última atualização:** — staleness indeterminável' }); continue; }
    const t = parseTs(m[1]);
    if (t && Date.now() - t.getTime() > 30 * DAY) W.push({ f: `docs/active/${s.id}/journal.md`, m: `SPEC ativa parada há >30 dias (Última atualização: ${m[1]}) — pause com motivo ou retome` });
  }
  // anti-fuga + integridade de evidência (D1/A4) — SEMPRE warn (stage1), nunca strict-fail
  for (const s of specs.filter((x) => x.phase === 'active')) {
    const pm = parseMain(readSafe(P(s.dir, 'main.md')));
    const crit = getCriteria(pm) || [];
    const porte = (pm.fields.Porte || 'M').toUpperCase();
    // (a) porte P com >3 critérios: sinais de porte M
    if (porte === 'P' && crit.length > 3) {
      W.push({ f: `docs/active/${s.id}/main.md`, m: `porte P com ${crit.length} critérios — sinais de porte M; considere: node scripts/specctl.mjs escalate ${s.id} M`, stage1: true });
    }
    // (b) critério com "verify: exit 0" sem entrada de LOG contendo "verify:" no journal: evidência sem rastro
    if (crit.some((c) => /verify:\s*exit 0/.test(c.raw))) {
      const jTxt = norm(readSafe(P(s.dir, 'journal.md')));
      const logPart = jTxt.includes('## LOG') ? jTxt.slice(jTxt.indexOf('## LOG')) : jTxt;
      if (!/verify:/.test(logPart)) {
        W.push({ f: `docs/active/${s.id}/main.md`, m: `critério com "verify: exit 0" sem entrada de LOG contendo "verify:" no journal — evidência sem rastro (R.6.1); re-verifique com node scripts/specctl.mjs verify ${s.id} --all`, stage1: true });
      }
    }
  }
  // claims ↔ active
  const activeIds = new Set(specs.filter((s) => s.phase === 'active').map((s) => s.id));
  const claimsDir = P(root, 'docs', 'claims');
  if (isDir(claimsDir)) {
    for (const fp of walkFiles(claimsDir, { exts: ['.md'] })) {
      const cid = path.basename(fp, '.md');
      if (activeIds.has(cid)) continue;
      const elsewhere = specs.find((s) => s.id === cid);
      if (elsewhere) W.push({ f: relOf(root, fp), m: `claim órfão: ${cid} está em ${elsewhere.phase}/ — remova o claim (transições via specctl fazem isso)` });
      // sem SPEC local: pode estar ativa em outra branch — é o design, não avisa
    }
    for (const id of activeIds) {
      if (!exists(claimPath(root, id))) W.push({ f: `docs/active/${id}`, m: 'ativação sem claim (R.11) — recrie: docs/claims/' + id + '.md (specctl activate faz isso)' });
    }
    // team: multi — claim existe local mas NÃO na base = invisível aos outros devs (a publicação atrasou)
    if (manifest(root).team === 'multi') {
      for (const id of activeIds) {
        const cp = claimPath(root, id);
        if (!exists(cp)) continue;
        const cTxt = read(cp);
        const base = ((/^\*\*Base:\*\*\s*(.+)$/m.exec(cTxt) || [])[1] || '').trim() || detectBaseBranch(root, currentBranch(root));
        if (!base || base === '—') continue;
        const rel = relOf(root, cp);
        const inBase = gitRun(['cat-file', '-e', `${base}:${rel.split(path.sep).join('/')}`], root);
        const inRemoteBase = inBase.ok ? inBase : gitRun(['cat-file', '-e', `origin/${base}:${rel.split(path.sep).join('/')}`], root);
        if (!inBase.ok && !inRemoteBase.ok) {
          W.push({ f: rel, m: `team=multi: claim de ${id} ainda NÃO publicado em '${base}' — os outros devs não veem o trabalho em voo (R.11). PR trivial: só docs/claims/ (specctl activate imprime os comandos)` });
        }
      }
    }
  }
  // decisões >180d ainda ativas
  for (const f of featureFiles(root)) {
    for (const line of norm(readSafe(f.path)).split('\n')) {
      const m = /(DEC-(\d{4})(\d{2})(\d{2})-\d{4}[\w-]*)/.exec(line);
      if (!m || /obsolet|substitu/i.test(line)) continue;
      const t = new Date(+m[2], +m[3] - 1, +m[4]);
      if (Date.now() - t.getTime() > 180 * DAY) W.push({ f: relOf(root, f.path), m: `decisão ativa há >180 dias: ${m[1]} — revalide ou marque obsoleta` });
    }
  }
}
function cmdAudit(flags) {
  const root = requireRoot();
  const E = [], W = [];
  auditBase(root, E, W);
  if (flags.deps) auditDeps(root, E, W);
  if (flags['main-gate']) {
    const act = activeSpecs(root);
    if (act.length) E.push({ f: 'docs/active/', m: `R.2 (gate de main): docs/active/ deve estar vazio — encontrado: ${act.map((s) => s.id).join(', ')}` });
  }
  if (flags.pr) auditPr(root, flags.base, E, W);
  for (const e of E) process.stderr.write(`ERRO  ${e.f}: ${e.m}\n`);
  if (W.length) {
    process.stdout.write('AVISOS (não bloqueiam archive/close/CI):\n');
    for (const w of W) process.stdout.write(`AVISO ${w.f}: ${w.m}\n`);
  }
  process.stdout.write(`\naudit: ${E.length} erro(s), ${W.length} aviso(s)\n`);
  process.exit(E.length ? 1 : 0);
}

// ---------------------------------------------------------------- brief / capsule / stamp

const HARD_BANS = [
  '1. R.6.2 — contrato binário: só o USUÁRIO aceita critério incompleto (marcador [aceito-incompleto: "citação literal" YYYY-MM-DD HH:MM]). NUNCA reduza escopo em silêncio.',
  '2. LOG do journal é append-only — NUNCA edite/reescreva entradas antigas; adicione nova entrada datada.',
  '3. docs/active/ vazio em main — toda SPEC ativa vive em branch de feature.',
  '4. Artefatos/temporários na pasta da SPEC — tmp/ (descartável) ou evidence/ (persistente); sem SPEC ativa: .scratch/.',
  '5. PROIBIDO varrer scripts/specctl.mjs ou re-ler docs/rules/* só para "garantir compliance" — os gates dizem o que falta (close <id> --dry). Ler a rule DA TAREFA no momento do uso (transição→lifecycle, artefato→formats) é o caminho CERTO, não viola este ban.',
];
function specSummary(root, s) {
  const pm = parseMain(readSafe(P(s.dir, 'main.md')));
  const crit = getCriteria(pm) || [];
  const done = crit.filter((c) => c.checked).length;
  return { pm, feats: splitList(pm.fields.Features || ''), done, total: crit.length };
}
// seção compacta "Próximo trabalho" do brief (§Integração no brief)
// activeNonEmpty=true → 1 linha-resumo (economia); senão as 3 linhas condicionais
function briefNextLines(root, disc, activeNonEmpty) {
  const openPrograms = disc.programs.filter((p) => p.state.open);
  const roadmapCount = (disc.roadmap.next ? 1 : 0) + disc.roadmap.later.length;
  if (activeNonEmpty) {
    return [`Backlog: ${openPrograms.length} programa(s) aberto(s), ${roadmapCount} no roadmap — \`specctl next\``];
  }
  const L = ['Próximo trabalho:'];
  const hadContent = L.length;
  // Programas: 1 SPEC destacada por programa (▶ pronto, senão ⏳ ativo) + contagem de bloqueados
  if (openPrograms.length) {
    const parts = openPrograms.map(({ prog, state }) => {
      const highlight = state.ready[0] || state.active[0];
      const mark = state.ready[0] ? '▶' : (state.active[0] ? '⏳' : '');
      let seg = `${prog.slug} (${state.done.length}/${state.total})`;
      if (highlight) seg += ` ${mark} ${highlight}`;
      if (state.blocked.length) seg += ` · 🔒${state.blocked.length}`;
      if (state.paused.length) seg += ` · ⏸${state.paused.length}`;
      return seg;
    });
    L.push(`- Programas: ${parts.join(' | ')}`);
  }
  // Roadmap: topo + "(+N)"
  if (disc.roadmap.next) {
    const extra = disc.roadmap.later.length ? ` (+${disc.roadmap.later.length})` : '';
    L.push(`- Roadmap ▶ ${disc.roadmap.next}${extra}`);
  }
  // Não-priorizadas: só a contagem
  if (disc.orphans.length) {
    L.push(`- Não-priorizadas: ${disc.orphans.length} (rode \`specctl next\` ou priorize em docs/ROADMAP.md)`);
  }
  return L.length > hadContent ? L : [];
}
function cmdBrief(flags) {
  const root = findRoot(process.cwd());
  if (!root) { out('[SDD v4] projeto sem docs/.spec-system.json — rode a skill spec-system-init.'); process.exit(0); }
  const man = manifest(root);
  const branch = currentBranch(root);
  const act = activeSpecs(root);
  const snapOf = (s) => {
    const jp = P(s.dir, 'journal.md');
    if (!exists(jp)) return '(journal.md ausente)';
    return norm(read(jp)).split('\n').slice(0, 60).join('\n');
  };
  // C4 — brief --agent <id>: bundle 1-call (compacto + main.md + SNAPSHOT + próximos passos, sem duplicar)
  if (flags.agent) {
    const spec = findSpec(root, String(flags.agent));
    const B = [];
    B.push(`[bundle ${spec.id} — 1-call p/ subagente · branch ${branch || '(git indisponível)'} · NOW=${now()}]`);
    B.push('');
    B.push('HARD BANS (TIER-0):');
    for (const b of HARD_BANS) B.push(b);
    B.push('');
    B.push('== main.md ==');
    B.push(norm(readSafe(P(spec.dir, 'main.md'))).replace(/\n+$/, ''));
    B.push('');
    B.push(`== SNAPSHOT (${spec.id}) ==`);
    B.push(snapOf(spec));
    B.push('== fim do SNAPSHOT ==');
    B.push('');
    B.push('Próximos passos:');
    try { B.push(checklistText(spec, closeStage(root, spec), true)); }
    catch { B.push(`fechar: node scripts/specctl.mjs close ${spec.id} --dry`); }
    out(B.join('\n'));
    process.exit(0);
  }
  const L = [];
  if (flags.compact) {
    L.push('HARD BANS (TIER-0):');
    for (const b of HARD_BANS) L.push(b);
    L.push('');
    L.push(`Branch: ${branch || '(git indisponível)'} · SPECs ativas: ${act.length ? act.map((s) => s.id).join(', ') : 'nenhuma'}`);
    if (act.length) { L.push(''); L.push(`== SNAPSHOT (${act[0].id}) ==`); L.push(snapOf(act[0])); }
    L.push('');
    L.push('(pré-compact: faça o flush — sobrescreva o SNAPSHOT e registre no LOG o que não pode se perder)');
    L.push('');
    L.push(`[SDD v4 · ${man.schema || SCHEMA} · NOW=${now()}]`);
    out(L.join('\n'));
    process.exit(0);
  }
  // ---- blocos ESTÁVEIS primeiro (E3+E5/C2): bans → referências → INDEX filtrado
  const activeIds = new Set(act.map((s) => s.id));
  const myFeats = new Set(act.flatMap((s) => specSummary(root, s).feats));
  L.push('HARD BANS (TIER-0):');
  for (const b of HARD_BANS) L.push(b);
  L.push('');
  L.push('Referências: criar/editar artefato → docs/rules/formats.md · transição de ciclo → docs/rules/lifecycle.md · programa/DAG → docs/rules/programs.md · interop/workspace → docs/rules/interop.md');
  // INDEX filtrado pelas Features da SPEC ativa (+ "outras: ver docs/INDEX.md")
  const idxAll = norm(readSafe(P(root, 'docs', 'INDEX.md'))).split('\n').filter((l) => l.startsWith('- '));
  L.push('');
  if (!idxAll.length) {
    L.push('INDEX (resumo):');
    L.push('(vazio — rode: node scripts/specctl.mjs index)');
  } else if (myFeats.size) {
    const mine = idxAll.filter((l) => { const m = /^-\s+\*\*([^*]+)\*\*/.exec(l); return m && myFeats.has(m[1].trim()); });
    L.push('INDEX (features desta SPEC):');
    L.push(...(mine.length ? mine : ['(nenhuma feature da SPEC no INDEX ainda)']));
    L.push('outras: ver docs/INDEX.md');
  } else {
    L.push('INDEX (resumo):');
    L.push(...idxAll.slice(0, 10));
    L.push('outras: ver docs/INDEX.md');
  }
  // ---- blocos VOLÁTEIS no fim: branch, SPECs ativas, SNAPSHOT, claims, próximo trabalho
  L.push('');
  L.push(`Branch: ${branch || '(git indisponível)'}`);
  if (!act.length) L.push('SPECs ativas: nenhuma (docs/active/ vazio)');
  else {
    for (const s of act) {
      const info = specSummary(root, s);
      L.push(`SPEC ativa: ${s.id} (${info.feats.join(', ') || 'sem features'}) — critérios ${info.done}/${info.total} [x]`);
    }
    if (act.length > 1) L.push('ATENÇÃO: múltiplas SPECs em docs/active/ — indique QUAL no prompt (R.9 exige escolha).');
    L.push('');
    L.push(`== SNAPSHOT (${act[0].id}) ==`);
    L.push(snapOf(act[0]));
    L.push('== fim do SNAPSHOT ==');
  }
  // claims em colisão
  const collisions = [];
  const claimsDir = P(root, 'docs', 'claims');
  if (isDir(claimsDir)) {
    for (const fp of walkFiles(claimsDir, { exts: ['.md'] })) {
      const cid = path.basename(fp, '.md');
      if (activeIds.has(cid)) continue;
      const txt = readSafe(fp);
      const cf = splitList((/^\*\*Features:\*\*\s*(.*)$/m.exec(txt) || [])[1] || '');
      const owner = (/^\*\*Owner:\*\*\s*(.*)$/m.exec(txt) || [])[1] || '?';
      if (cf.some((x) => myFeats.has(x))) collisions.push(`- ${cid} (${owner}) — features: ${cf.join(', ')}`);
    }
  }
  L.push('');
  L.push(collisions.length ? 'Claims em COLISÃO (mesma feature em voo em outra branch):' : 'Claims em colisão: nenhuma');
  for (const c of collisions) L.push(c);
  // itens deferidos com autorização (R.6.2) — visibilidade sem abrir archive
  const defTxt = readSafe(P(root, 'docs', 'DEFERRED.md'));
  const defCount = defTxt ? (defTxt.match(/^- SPEC-/gm) || []).length : 0;
  if (defCount) L.push(`Deferidos (R.6.2, com citação): ${defCount} item(ns) — ver docs/DEFERRED.md`);
  // Próximo trabalho (formato compacto) — só quando há future/ ou programa aberto
  const disc = discoveryModel(root);
  if (disc.hasFuture || disc.anyOpenProgram) {
    const nextLines = briefNextLines(root, disc, act.length > 0);
    if (nextLines.length) { L.push(''); L.push(...nextLines); }
  }
  L.push('R.9: classifique a 1ª linha da sua resposta: [continuidade: SPEC-x] | [nova] | [livre]');
  // NOW no FIM (bloco volátil por último)
  L.push('');
  L.push(`[SDD v4 · ${man.schema || SCHEMA} · NOW=${now()} · Branch: ${branch || '—'}]`);
  out(L.join('\n'));
  process.exit(0);
}
// modelo de descoberta compartilhado por `next` e `brief`
// { programs:[{prog,state}], roadmap:{next,later}, orphans:[SPEC-id], hasFuture, anyOpenProgram }
function discoveryModel(root) {
  const specs = listSpecs(root);
  const statusOf = makeStatusOf(specs);
  const progs = parsePrograms(root);
  const programs = progs
    .map((prog) => ({ prog, state: computeProgramState(prog, statusOf) }))
    .sort((a, b) => {
      if (a.state.open !== b.state.open) return a.state.open ? -1 : 1;
      return a.prog.slug < b.prog.slug ? -1 : 1;
    });
  const future = futureDraftSpecs(root); // [{ id, dir }] draft em future/
  const futureDraftIds = new Set(future.map((f) => f.id));
  // programa de cada SPEC vem do **Programa:** do main.md
  const programOf = new Map();
  for (const f of future) {
    const prog = (parseMain(readSafe(P(f.dir, 'main.md'))).fields.Programa || '—').trim();
    programOf.set(f.id, prog && prog !== '—' ? prog : null);
  }
  // ROADMAP: percorre a ordem; "próximo" = 1ª entrada em future draft; "depois" = as seguintes ainda-future draft
  const roadmapIds = parseRoadmap(root);
  const roadmapFuture = roadmapIds.filter((id) => futureDraftIds.has(id));
  const roadmap = { next: roadmapFuture[0] || null, later: roadmapFuture.slice(1) };
  const inRoadmap = new Set(roadmapIds);
  // órfã = future draft, SEM **Programa:**, E não citada no ROADMAP (nunca auto-ordenada — só listada)
  const orphans = future
    .filter((f) => !programOf.get(f.id) && !inRoadmap.has(f.id))
    .map((f) => f.id)
    .sort((a, b) => (a < b ? -1 : 1));
  const anyOpenProgram = programs.some((p) => p.state.open);
  return { programs, roadmap, orphans, hasFuture: future.length > 0, anyOpenProgram };
}

function cmdNext(root, flags) {
  root = root || requireRoot();
  const model = discoveryModel(root);
  let programs = model.programs;
  if (flags.program) {
    const slug = String(flags.program).trim();
    if (!programs.some((p) => p.prog.slug === slug)) {
      die(`programa '${slug}' não existe em docs/programs/ — programas: ${programs.map((p) => p.prog.slug).join(', ') || '(nenhum)'}`);
    }
    programs = programs.filter((p) => p.prog.slug === slug);
  }
  const L = [];
  L.push('=== Próximo trabalho ===');
  // seção PROGRAMAS (ordem = dependências)
  const progLines = [];
  for (const { prog, state } of programs) {
    for (const id of state.ready) progLines.push(`  ▶ pronto:   ${id} (programa ${prog.slug})`);
    for (const id of state.active) {
      const owner = claimOwner(root, id);
      progLines.push(`  ⏳ ativo:    ${id} (programa ${prog.slug})${owner ? ` [${owner}]` : ''}`);
    }
    for (const b of state.blocked) progLines.push(`  🔒 bloqueado: ${b.id} (programa ${prog.slug} — aguarda ${b.waits.join(', ')})`);
    for (const id of state.paused) progLines.push(`  ⏸ pausado:  ${id} (programa ${prog.slug} — retomar: specctl resume ${id})`);
  }
  if (progLines.length) {
    L.push('');
    L.push('PROGRAMAS (ordem = dependências):');
    L.push(...progLines);
  }
  // seção ROADMAP (ordem = docs/ROADMAP.md) — só quando não filtrando por programa
  if (!flags.program && (model.roadmap.next || model.roadmap.later.length)) {
    L.push('');
    L.push('ROADMAP (ordem = docs/ROADMAP.md):');
    if (model.roadmap.next) L.push(`  ▶ próximo:  ${model.roadmap.next}`);
    if (model.roadmap.later.length) L.push(`  · depois:   ${model.roadmap.later.join(', ')}`);
  }
  // seção BACKLOG NÃO-PRIORIZADO (órfãs) — só quando não filtrando por programa
  if (!flags.program && model.orphans.length) {
    L.push('');
    L.push('BACKLOG NÃO-PRIORIZADO (future sem programa e fora do ROADMAP — defina ordem em docs/ROADMAP.md):');
    L.push(`  ${model.orphans.join(', ')}`);
  }
  // tudo vazio
  const hasContent = progLines.length || (!flags.program && (model.roadmap.next || model.roadmap.later.length || model.orphans.length));
  if (!hasContent) {
    if (flags.program) L.push('\nNada pendente neste programa: todos os nós estão concluídos ou pausados.');
    else L.push('\nNada pendente: docs/future/ vazio e nenhum programa aberto.');
  }
  out(L.join('\n'));
  process.exit(0);
}
// owner do claim de um SPEC ativo (docs/claims/<id>.md), se houver — senão null
function claimOwner(root, id) {
  const fp = claimPath(root, id);
  if (!exists(fp)) return null;
  const owner = (/^\*\*Owner:\*\*\s*(.*)$/m.exec(readSafe(fp)) || [])[1] || '';
  return owner.trim() || null;
}

function cmdCapsule() {
  const root = findRoot(process.cwd());
  if (!root) process.exit(0);
  const man = manifest(root);
  const act = activeSpecs(root);
  let activePart = '—';
  if (act.length === 1) {
    const info = specSummary(root, act[0]);
    activePart = `${act[0].id}${info.feats.length ? ` (${info.feats.join(', ')})` : ''}`;
  } else if (act.length > 1) {
    activePart = `${act.map((s) => s.id).join(', ')} — MÚLTIPLAS: escolha 1 no prompt`;
  }
  // interop inline: a cápsula É o mecanismo da substituição de caminho (rules/interop.md) — skills prd
  // escrevem na pasta da SPEC, não em tasks/prd-*/; só injeta com SPEC ativa única (senão ambíguo)
  const inlineNote = man.interop === 'inline' && act.length === 1
    ? ` · WORKSPACE: docs/active/${act[0].id}/ — substitua ./tasks/prd-<slug>/ por este caminho em TODOS os passos (leitura E escrita)`
    : '';
  const teamPart = man.team === 'multi' ? ' · team=multi' : '';
  let cap = `NOW=${now()} · ACTIVE=${activePart} · workspace=${man.interop || 'none'}${teamPart}${inlineNote} · bans: R.6.2/append-only/main-limpa/tmp · classifique na 1ª linha: [continuidade|nova|livre]`;
  if (bytesOf(cap) > 800) {
    activePart = act.length ? act[0].id : '—';
    cap = `NOW=${now()} · ACTIVE=${activePart} · workspace=${man.interop || 'none'}${teamPart}${inlineNote} · bans: R.6.2/append-only/main-limpa/tmp · classifique na 1ª linha: [continuidade|nova|livre]`;
  }
  out(cap);
  process.exit(0);
}
function cmdStamp() {
  const root = requireRoot();
  const commit = git(['rev-parse', '--short', 'HEAD'], root);
  const branch = git(['rev-parse', '--abbrev-ref', 'HEAD'], root);
  out(`NOW=${now()} · commit=${commit} · branch=${branch}`);
}

// ---------------------------------------------------------------- verify

function cmdVerify(pos, flags) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  const mainPath = P(spec.dir, 'main.md');
  const pm = parseMain(read(mainPath));
  const crit = getCriteria(pm);
  if (!crit) die(`${spec.id}: sem seção "## Critério de aceite"`);
  const targets = crit.filter((c) => {
    const m = /\|\s*verify:\s*`([^`]+)`/.exec(c.raw);
    if (!m || m[1].includes('<')) return false;
    return flags.all ? true : !c.checked;
  });
  if (!targets.length) { out('nada a verificar — nenhum critério pendente com `verify:` executável (use --all para reverificar)'); process.exit(0); }
  const short = git(['rev-parse', '--short', 'HEAD'], root); // exige git: evidência registra commit
  const lines = norm(read(mainPath)).split('\n');
  let fails = 0;
  const summary = [];
  for (const c of targets) {
    const cmd = /\|\s*verify:\s*`([^`]+)`/.exec(c.raw)[1];
    process.stdout.write(`verify: ${truncate(c.text, 60)}\n  $ ${cmd}\n`);
    let ok = false, detail = '';
    try { execSync(cmd, { cwd: root, stdio: 'pipe', timeout: 300000 }); ok = true; }
    catch (e) { detail = truncate(String(e.stderr || e.stdout || e.message || ''), 300); }
    if (ok) {
      let line = lines[c.line];
      line = line.replace(/\s*\(\d{4}-\d{2}-\d{2} \d{2}:\d{2}, commit `[^`]*`, verify: exit 0\)/, '');
      const vm = /^(\s*-\s*)\[(?: |x|X)\]\s*(.*?)(\s*\|\s*verify:.*)$/.exec(line);
      if (vm) lines[c.line] = `${vm[1]}[x] ${vm[2]} (${now()}, commit \`${short}\`, verify: exit 0)${vm[3]}`;
      process.stdout.write('  PASS — marcado [x] com evidência\n');
      summary.push(`PASS: ${truncate(c.text, 60)}`);
    } else {
      fails++;
      process.stdout.write(`  FAIL — critério permanece [ ]\n${detail ? '  ' + detail + '\n' : ''}`);
      summary.push(`FAIL: ${truncate(c.text, 60)}`);
    }
  }
  writeFile(mainPath, lines.join('\n'));
  appendLog(spec.dir, 'nota', `verify: ${targets.length - fails}/${targets.length} critérios passaram (commit \`${short}\`)`, summary.map((s) => `- ${s}`).join('\n'));
  // n/n evidenciados → antecipa a descoberta do fechamento (A1)
  const afterCrit = getCriteria(parseMain(lines.join('\n'))) || [];
  if (!fails && afterCrit.length && afterCrit.every((c) => c.checked || ACEITO_RE.test(c.raw))) {
    out(`próximo: node scripts/specctl.mjs close ${spec.id} --dry`);
  }
  process.exit(fails ? 1 : 0);
}

// ---------------------------------------------------------------- scribe e fechamento (v4.1 — Pilares A/B)

// B1+ — rodapé factual de máquina para entradas de LOG (2 chamadas git; falha ⇒ omite silenciosamente)
function gitFooter(root) {
  const head = gitRun(['rev-parse', '--short', 'HEAD'], root);
  if (!head.ok) return '';
  const diff = gitRun(['diff', '--shortstat', 'HEAD'], root);
  if (!diff.ok) return '';
  const stat = diff.out.trim();
  return stat ? `⎿ commit ${head.out}+dirty · ${stat}` : `⎿ commit ${head.out}`;
}
// entrada de texto do scribe: valida UTF-8, remove BOM e normaliza CRLF→LF
function sanitizeBody(buf, label) {
  let s;
  try { s = new TextDecoder('utf-8', { fatal: true }).decode(buf); }
  catch { die(`${label}: conteúdo não é UTF-8 válido — reenvie como UTF-8 (sem BOM)`); }
  return s.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n').replace(/\s+$/, '');
}

const LOG_HELP = `uso: node scripts/specctl.mjs log <id> <tipo> "título" [--stdin|--body-file <f>]
tipos: ${LOG_TYPES.join(' | ')}
título: sempre 1 linha. Corpo (opcional, multilinha) por --stdin ou --body-file:
  bash:       node scripts/specctl.mjs log SPEC-x decisão "Título" --stdin <<'EOF'
              corpo da entrada…
              EOF
  PowerShell: @'
              corpo da entrada…
              '@ | node scripts/specctl.mjs log SPEC-x decisão "Título" --stdin
  arquivo:    node scripts/specctl.mjs log SPEC-x decisão "Título" --body-file nota.md`;

function cmdLog(pos, flags) {
  const root = requireRoot();
  if (!pos[0] || !pos[1] || pos[2] === undefined) die(`log exige <id> <tipo> "título".\n${LOG_HELP}`);
  const spec = findSpec(root, pos[0]);
  const tipo = pos[1];
  if (!LOG_TYPES.includes(tipo)) die(`tipo inválido '${tipo}' — gramática completa dos tipos: ${LOG_TYPES.join(' | ')}\n${LOG_HELP}`);
  const titulo = String(pos[2]);
  if (/[\r\n]/.test(titulo)) die(`título é single-line na gramática do LOG — detalhe multilinha vai no corpo (--stdin/--body-file).\n${LOG_HELP}`);
  if (!titulo.trim()) die(`título vazio.\n${LOG_HELP}`);
  if (flags.stdin && flags['body-file']) die('use --stdin OU --body-file, não ambos');
  let body = '';
  if (flags.stdin) body = sanitizeBody(fs.readFileSync(0), 'stdin');
  else if (flags['body-file']) {
    const bf = path.resolve(String(flags['body-file']));
    if (!exists(bf)) die(`--body-file: arquivo não existe: ${flags['body-file']}`);
    body = sanitizeBody(fs.readFileSync(bf), String(flags['body-file']));
  }
  const stored = [body, gitFooter(root)].filter(Boolean).join('\n');
  const heading = appendLog(spec.dir, tipo, titulo, stored);
  // eco da entrada gravada (≤2 linhas): heading + 1ª linha do corpo/rodapé
  out(heading);
  const first = stored.split('\n').find((l) => l.trim());
  if (first) out(first);
}

function cmdCheck(pos, flags) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  if (spec.phase !== 'active') die(`check: ${spec.id} está em ${spec.phase}/ — evidência de critério só em SPEC ativa`);
  const n = parseInt(pos[1], 10);
  const mainPath = P(spec.dir, 'main.md');
  const pm = parseMain(read(mainPath));
  const crit = getCriteria(pm);
  if (!crit || !crit.length) die(`${spec.id}: seção "## Critério de aceite" sem checkboxes — nada a estampar`);
  if (!Number.isInteger(n) || n < 1 || n > crit.length) {
    die(`uso: node scripts/specctl.mjs check <id> <n> [--evidence "..."] — n é 1-based; ${spec.id} tem ${crit.length} critério(s)`);
  }
  const c = crit[n - 1];
  if (hasVerifyTag(c.raw)) die(`critério ${n} tem verify: — rota: node scripts/specctl.mjs verify ${spec.id}`);
  const ev = flags.evidence ? String(flags.evidence).trim() : '';
  if (/[\r\n]/.test(ev)) die('--evidence é single-line — detalhe longo vai no LOG (specctl log) ou em evidence/');
  if (/verify:/.test(ev)) die('check NUNCA escreve o token "verify:" — evidência executável usa: node scripts/specctl.mjs verify');
  const lines = norm(read(mainPath)).split('\n');
  const allClosedMsg = () => {
    const after = getCriteria(parseMain(lines.join('\n'))) || [];
    if (after.length && after.every((x) => x.checked || ACEITO_RE.test(x.raw))) {
      out(`todos evidenciados — próximo: node scripts/specctl.mjs close ${spec.id} --dry`);
    }
  };
  if (c.checked) {
    out(lines[c.line].trim());
    out(`critério ${n} já está [x] — nada a fazer`);
    allClosedMsg();
    process.exit(0);
  }
  const short = git(['rev-parse', '--short', 'HEAD'], root); // evidência registra commit (R.6)
  const m = /^(\s*-\s*)\[ \]\s*(.*?)\s*$/.exec(lines[c.line]);
  if (!m) die(`critério ${n}: linha fora do formato "- [ ] ..." — corrija o main.md antes de estampar`);
  lines[c.line] = `${m[1]}[x] ${m[2]} (${now()}, commit \`${short}\`${ev ? `, evidence: ${ev}` : ''})`;
  writeFile(mainPath, lines.join('\n'));
  out(lines[c.line].trim());
  allClosedMsg();
}

// medição canônica do digest (A2/2c): bytes LF-normalizados (lfText: strip CR/BOM) + comentários HTML descontados
function digestMeasure(s) {
  return bytesOf(lfText(s).replace(/^\uFEFF/, '').replace(/<!--[\s\S]*?-->/g, ''));
}
// extração estrutural (formato §3.4) — a ferramenta trunca por prioridade até caber ≤2.000B
function genDigest(root, spec, o = {}) {
  const pm = parseMain(readSafe(P(spec.dir, 'main.md')));
  const f = pm.fields;
  const titulo = ((/^# SPEC-[\d-]+:\s*(.*)$/.exec(pm.lines[0] || '') || [])[1] || '').trim();
  const crit = getCriteria(pm) || [];
  const done = crit.filter((c) => c.checked).length;
  const j = norm(readSafe(P(spec.dir, 'journal.md')));
  let onde = '—';
  for (const m of j.matchAll(/\*\*Onde tô:\*\*\s*(.+)/g)) onde = m[1].trim(); // "Onde tô" final do SNAPSHOT
  // "Entregue" = a entrada [conclusão] do LOG (autoritativa, escrita no fechamento) tem prioridade sobre o "Onde tô"
  // do SNAPSHOT — que pode estar stale (placeholder do template) numa SPEC fechada só via scribe. Bug achado no bench porte-P.
  let conclusao = '';
  for (const m of j.matchAll(/^## \d{4}-\d{2}-\d{2} \d{2}:\d{2} — (?:\[MARCO\] )?\[conclusão\]\s*(.+)$/gm)) conclusao = m[1].trim();
  if (SNAP_PLACEHOLDER.test(onde) || onde === '—') onde = conclusao || (SNAP_PLACEHOLDER.test(onde) ? '(ver critérios/decisões)' : onde);
  const dec = [];
  for (const m of j.matchAll(/^## \d{4}-\d{2}-\d{2} \d{2}:\d{2} — (?:\[MARCO\] )?\[decisão\]\s*(.+)$/gm)) dec.push(truncate(m[1], 100));
  const porte = (f.Porte || 'M').toUpperCase();
  const cfField = (f['Commit final'] || '—').trim();
  const commitFinal = cfField !== '—' ? cfField : (o.commitFinal || '—');
  const ccField = (f['Concluída'] || '—').trim();
  const concluida = ccField !== '—' ? ccField : (o.concluida || '—');
  let resumo = (f.Resumo || '—').trim();
  let entregue = onde;
  let decs = dec.slice(0, 8);
  const build = () => {
    if (porte === 'P') { // porte P: 3-5 linhas, sem passo do modelo
      return `# Digest — ${spec.id}\n${DIGEST_STUB_NOTE}\n**Resumo:** ${resumo} · **Features:** ${f.Features || '—'} · **Commit final:** ${commitFinal}\n**Entregue:** ${entregue} (critérios ${done}/${crit.length}, concluída ${concluida})\n`;
    }
    const L = [`# Digest — ${spec.id}${titulo ? `: ${truncate(titulo, 80)}` : ''}`, DIGEST_STUB_NOTE, ''];
    L.push(`**Resumo:** ${resumo}`);
    L.push(`**Porte:** ${porte} · **Features:** ${f.Features || '—'} · **Criada:** ${f.Criada || '—'} · **Concluída:** ${concluida}`);
    L.push(`**Critérios:** ${done}/${crit.length} fechados · **Commit final:** ${commitFinal}`);
    L.push(`**Entregue:** ${entregue}`);
    if (decs.length) { L.push('**Decisões:**'); for (const d of decs) L.push(`- ${d}`); }
    L.push('');
    L.push('_Contexto completo: journal.md + main.md nesta pasta._');
    return L.join('\n') + '\n';
  };
  let txt = build();
  while (digestMeasure(txt) > 2000) { // nunca devolve o corte pro modelo: decisões → entregue → resumo
    if (decs.length) decs.pop();
    else if (entregue.length > 60) entregue = truncate(entregue, Math.max(60, Math.floor(entregue.length / 2)));
    else if (resumo.length > 60) resumo = truncate(resumo, Math.max(60, Math.floor(resumo.length / 2)));
    else break;
    txt = build();
  }
  while (digestMeasure(txt) > 2000) txt = txt.slice(0, -16); // salvaguarda dura da garantia
  if (!txt.endsWith('\n')) txt += '\n';
  return txt;
}
function cmdDigest(pos, flags) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  const dgPath = P(spec.dir, 'digest.md');
  const rel = relOf(root, dgPath);
  if (flags.stdin || flags.file) { // refino do modelo: re-validado com resposta acionável
    if (flags.stdin && flags.file) die('use --stdin OU --file, não ambos');
    let raw;
    if (flags.stdin) raw = fs.readFileSync(0);
    else {
      const fsrc = path.resolve(String(flags.file));
      if (!exists(fsrc)) die(`--file: arquivo não existe: ${flags.file}`);
      raw = fs.readFileSync(fsrc);
    }
    let txt = sanitizeBody(raw, flags.stdin ? 'stdin' : String(flags.file));
    if (!txt.endsWith('\n')) txt += '\n';
    const b = digestMeasure(txt);
    if (b > 2000) die(`digest recusado: ${b}B > 2000B: corte ~${b - 2000}B e reenvie (medição LF, comentários HTML descontados)`);
    writeFile(dgPath, txt);
    out(`digest gravado: ${b}B (≤2000) — ${rel}`);
    return;
  }
  if (exists(dgPath) && !flags.fix) {
    const b = digestMeasure(read(dgPath));
    if (b > 2000) die(`digest.md existe com ${b}B > 2000B — re-gere dentro do cap: node scripts/specctl.mjs digest ${spec.id} --fix`);
    die(`digest.md já existe (${b}B, dentro do cap) — refine via --stdin/--file ou re-gere: node scripts/specctl.mjs digest ${spec.id} --fix`);
  }
  const txt = genDigest(root, spec);
  writeFile(dgPath, txt);
  out(txt.replace(/\n$/, ''));
  out(`\ndigest: ${digestMeasure(txt)}B (≤2000) — gravado em ${rel}`);
}

// ---- rollup: ferramenta MANUAL/opcional (não é enforcement) — move blocos INTEIROS antigos p/ .history.md até a feature caber no alvo, para enxugar o auto-load N1 quando o AUTOR quiser. Tamanho de feature não é lintado nem bloqueado.
const FEATURE_CAP = 8000; // alvo do rollup manual, não um teto lintado
const ROLLUP_ELIG_RE = /delta de estado|hist[óo]rico/i;
const ROLLUP_LIVE_RE = /decis[õo]es arquiteturais ativas|^\s*estado atual/i;
function featurePathOf(root, area) { return P(root, 'docs', 'features', ...area.split('/')) + '.md'; }
// blocos line-oriented elegíveis: itens de lista COM SPEC-id em seções de delta/histórico ou gotchas;
// NUNCA em "Decisões arquiteturais ativas"/"Estado atual" (conteúdo vivo) — ordenados do mais antigo
function rollupBlocks(lines) {
  const blocks = [];
  let h2 = '', h3 = '';
  for (let i = 0; i < lines.length; i++) {
    const hm = /^(#{2,3})\s+(.*)$/.exec(lines[i]);
    if (hm) { if (hm[1].length === 2) { h2 = hm[2]; h3 = ''; } else h3 = hm[2]; continue; }
    if (!/^-\s/.test(lines[i])) continue;
    const eligible = ROLLUP_ELIG_RE.test(h3) || ROLLUP_ELIG_RE.test(h2) || /^gotchas/i.test(h2);
    const live = (ROLLUP_LIVE_RE.test(h2) || ROLLUP_LIVE_RE.test(h3)) && !ROLLUP_ELIG_RE.test(h3);
    if (!eligible || live) continue;
    let j = i + 1;
    while (j < lines.length && !/^-\s/.test(lines[j]) && !/^#{1,6}\s/.test(lines[j]) && /^\s+\S/.test(lines[j])) j++;
    const text = lines.slice(i, j).join('\n');
    const ids = [...text.matchAll(/\bSPEC-(\d{8}-\d{4})/g)].map((m) => m[1]);
    if (ids.length) blocks.push({ start: i, end: j, key: ids.sort()[0], text });
    i = j - 1;
  }
  return blocks.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : a.start - b.start));
}
function rollupArea(root, area) {
  const fp = featurePathOf(root, area);
  if (!exists(fp)) die(`docs/features/${area}.md não existe — áreas em docs/INDEX.md`);
  const lines = norm(read(fp)).split('\n');
  const rebuild = (removed) => lines.filter((_, i) => !removed.has(i)).join('\n').replace(/\n{3,}/g, '\n\n');
  let content = rebuild(new Set());
  if (lfBytes(content) <= FEATURE_CAP) return { moved: 0, bytes: lfBytes(content), fit: true };
  const removed = new Set();
  const movedBlocks = [];
  for (const b of rollupBlocks(lines)) {
    if (lfBytes(content) <= FEATURE_CAP) break;
    for (let i = b.start; i < b.end; i++) removed.add(i);
    movedBlocks.push(b);
    content = rebuild(removed);
  }
  const bytes = lfBytes(content);
  if (movedBlocks.length) {
    const histPath = fp.replace(/\.md$/, '.history.md');
    let hist = exists(histPath) ? norm(read(histPath))
      : `# History — ${area}\n\n> Rollup de docs/features/${area}.md (R.16): blocos movidos pelo specctl, do mais antigo ao mais novo. Não reintegrar — o conteúdo vivo continua na feature.\n`;
    if (!hist.endsWith('\n')) hist += '\n';
    hist += `\n## Rollup ${now()} (${movedBlocks.length} bloco(s))\n\n${movedBlocks.map((b) => b.text).join('\n')}\n`;
    writeFile(histPath, hist);
    writeFile(fp, content.endsWith('\n') ? content : content + '\n');
  }
  return { moved: movedBlocks.length, bytes, fit: bytes <= FEATURE_CAP };
}
function cmdRollup(pos) {
  const root = requireRoot();
  const area = pos[0];
  if (!area) die('uso: node scripts/specctl.mjs rollup <area> — move blocos antigos p/ docs/features/<area>.history.md até ≤8.000B');
  const r = rollupArea(root, area);
  out(`rollup: ${r.moved} bloco(s) → docs/features/${area}.history.md${r.moved ? '' : ' (nada movido)'}`);
  out(r.fit
    ? `docs/features/${area}.md: ${r.bytes} bytes (≤${FEATURE_CAP})`
    : `docs/features/${area}.md: ${r.bytes} bytes — mínimo atingível sem tocar seções vivas (> ${FEATURE_CAP}); reduza "Estado atual"/"Decisões arquiteturais ativas" manualmente`);
}

// ---- Porte com dente (D2): escalate one-way; rebaixar exige citação literal do usuário
const PORTE_RANK = { P: 1, M: 2, G: 3 };
function cmdEscalate(pos) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  if (spec.phase === 'archive' || spec.phase === 'discard') die(`escalate: ${spec.id} está em ${spec.phase}/ — Porte só muda em SPEC aberta`);
  const alvo = String(pos[1] || '').toUpperCase();
  if (!['M', 'G'].includes(alvo)) die('uso: node scripts/specctl.mjs escalate <id> <M|G> (one-way: P→M→G)');
  const mainPath = P(spec.dir, 'main.md');
  const cur = (parseMain(read(mainPath)).fields.Porte || 'M').toUpperCase();
  if (!PORTE_RANK[cur]) die(`Porte atual inválido no main.md: '${cur}' — corrija para P | M | G`);
  if (PORTE_RANK[alvo] <= PORTE_RANK[cur]) {
    die(`escalate é ONE-WAY (P→M→G): ${cur} → ${alvo} não é escalação. Rebaixar é decisão do USUÁRIO: node scripts/specctl.mjs deescalate ${spec.id} <P|M> --cita "citação literal do usuário"`);
  }
  writeFile(mainPath, setField(read(mainPath), 'Porte', alvo));
  appendLog(spec.dir, 'nota', `Porte escalado ${cur} → ${alvo}`, gitFooter(root));
  out(`Porte: ${cur} → ${alvo} (${spec.id}) — [nota] de escalação registrada no LOG`);
}
function cmdDeescalate(pos, flags) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  if (spec.phase === 'archive' || spec.phase === 'discard') die(`deescalate: ${spec.id} está em ${spec.phase}/ — Porte só muda em SPEC aberta`);
  const alvo = String(pos[1] || '').toUpperCase();
  if (!['P', 'M'].includes(alvo)) die('uso: node scripts/specctl.mjs deescalate <id> <P|M> --cita "citação literal do usuário"');
  const cita = flags.cita ? String(flags.cita).trim() : '';
  if (!cita) die('deescalate exige --cita "citação literal do usuário" — rebaixar Porte é decisão do USUÁRIO (padrão aceito-incompleto), nunca do agente');
  const mainPath = P(spec.dir, 'main.md');
  const cur = (parseMain(read(mainPath)).fields.Porte || 'M').toUpperCase();
  if (PORTE_RANK[alvo] >= PORTE_RANK[cur]) die(`deescalate rebaixa o Porte: ${cur} → ${alvo} não é rebaixamento — para subir use: node scripts/specctl.mjs escalate ${spec.id} ${alvo}`);
  writeFile(mainPath, setField(read(mainPath), 'Porte', alvo));
  const body = [`[aceito-incompleto: "${cita.replace(/"/g, "'")}" ${now()}]`, gitFooter(root)].filter(Boolean).join('\n');
  appendLog(spec.dir, 'nota', `Porte rebaixado ${cur} → ${alvo} (autorizado pelo usuário)`, body);
  out(`Porte: ${cur} → ${alvo} (${spec.id}) — citação do usuário registrada no LOG`);
}

// ---- close (A1): stage → validate-ALL → apply (all-or-nothing, idempotente)
// STAGE: zero mutação — separa bloqueios (exigem humano/modelo) de passos automatizáveis
function closeStage(root, spec) {
  const pm = parseMain(read(P(spec.dir, 'main.md')));
  const crit = getCriteria(pm) || [];
  const blockers = [], autos = [];
  let verifyPending = 0;
  if (!crit.length) blockers.push('seção "## Critério de aceite" sem checkboxes — contrato R.6.2 vazio');
  crit.forEach((c, i) => {
    const n = i + 1;
    if (hasVerifyTag(c.raw)) {
      const m = /\|\s*verify:\s*`([^`]+)`/.exec(c.raw);
      const runnable = m && !m[1].includes('<');
      if (!c.checked && !ACEITO_RE.test(c.raw)) {
        if (runnable) { verifyPending++; autos.push(`critério ${n} com verify: pendente — será executado no close`); }
        else blockers.push(`critério ${n} com verify: placeholder — preencha o comando real (ou fluxo R.6.2): "${truncate(c.text, 50)}"`);
      }
    } else if (!c.checked && !ACEITO_RE.test(c.raw)) {
      blockers.push(`critério ${n} aberto sem evidência: "${truncate(c.text, 50)}" — rota: node scripts/specctl.mjs check ${spec.id} ${n} ou fluxo R.6.2 (item a item, só o USUÁRIO aceita incompleto)`);
    } else if (c.checked && !hasTs(c.raw)) {
      blockers.push(`critério ${n} [x] sem timestamp (R.6): "${truncate(c.text, 50)}" — evidencie via check/verify`);
    }
  });
  const jp = P(spec.dir, 'journal.md');
  const jtxt = exists(jp) ? norm(readSafe(jp)) : '';
  if (!jtxt || !/^## \d{4}-\d{2}-\d{2} \d{2}:\d{2} — (?:\[MARCO\] )?\[conclusão\]/m.test(jtxt)) {
    blockers.push(`[conclusão] ausente no LOG — rota: node scripts/specctl.mjs log ${spec.id} conclusão "o que foi entregue"`);
  }
  // SNAPSHOT ainda em placeholder do template = não reflete a conclusão; o digest gerado herdaria o lixo ("Entregue: nada feito ainda")
  const snapEnd = jtxt.search(/^## LOG\b/m);
  if (SNAP_PLACEHOLDER.test(snapEnd >= 0 ? jtxt.slice(0, snapEnd) : jtxt)) {
    blockers.push(`SNAPSHOT ainda com placeholder do template ("Onde tô/Próximo passo/Fase") — sobrescreva o SNAPSHOT refletindo a conclusão antes de fechar (o digest é gerado dele)`);
  }
  const feats = splitList(pm.fields.Features || '');
  if (!feats.length) blockers.push('**Features:** vazio — R.4/R.7 exigem vínculo a feature');
  for (const ft of feats) {
    const r = featureConcludedOk(root, ft, spec.id);
    if (!r.ok) blockers.push(r.why);
  }
  const dg = P(spec.dir, 'digest.md');
  if (!exists(dg)) autos.push('digest.md ausente — será gerado no close (≤2.000B)');
  else {
    const b = digestMeasure(read(dg));
    if (b > 2000) autos.push(`digest.md com ${b}B > 2000B — será re-gerado no close`);
  }
  // (sem auto-rollup de feature no close: tamanho de feature não é gerido pelo harness — rollup é manual/opcional)
  const closeTestCmd = ((manifest(root).commands || {}).test || '').trim();
  if (closeTestCmd) autos.push(`suíte do projeto roda 1× no close (${truncate(closeTestCmd, 40)}) — falha aborta sem mover nada`);
  return { blockers, autos, feats, verifyPending };
}
// checklist ordenado (≤1,2KB) — mesmo texto no --dry e no close bloqueado (A1: --dry opcional e inofensivo)
function checklistText(spec, st, dry) {
  const items = [...st.blockers.map((b) => `✗ ${b}`), ...st.autos.map((a) => `▸ ${a}`)];
  const head = `== close ${spec.id}${dry ? ' --dry' : ''} — ${items.length} pendência(s) ==`;
  const foot = st.blockers.length
    ? `pronto: NÃO — resolva ${st.blockers.length} bloqueio(s) (✗) e rode: node scripts/specctl.mjs close ${spec.id}`
    : `pronto: SIM — os passos ▸ são automáticos: node scripts/specctl.mjs close ${spec.id}`;
  const L = [head, ...items, foot];
  let omitted = 0;
  while (bytesOf(L.join('\n')) > 1100 && L.length > 2) { L.splice(L.length - 2, 1); omitted++; }
  if (omitted) L.splice(L.length - 1, 0, `… +${omitted} pendência(s) omitida(s)`);
  return L.join('\n');
}
function cmdClose(pos, flags) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  if (spec.phase === 'archive') { out(`close: ${spec.id} já está em docs/archive/ — nada a fazer (idempotente)`); process.exit(0); }
  if (spec.phase === 'discard') die(`close: ${spec.id} está em discard/ — SPEC descartada não fecha`);
  if (spec.phase === 'future') {
    const st0 = parseMain(readSafe(P(spec.dir, 'main.md'))).fields.Status || 'draft';
    die(`close exige SPEC em active/ — ${spec.id} está em future/ (status ${st0}). Rota: node scripts/specctl.mjs ${st0 === 'paused' ? 'resume' : 'activate'} ${spec.id}, termine o trabalho e rode o close.`);
  }
  const st = closeStage(root, spec);
  if (flags.dry) { out(checklistText(spec, st, true)); process.exit(st.blockers.length ? 1 : 0); }
  if (st.blockers.length) { out(checklistText(spec, st, false)); process.exit(1); }
  // ---- APPLY (só chega aqui com validações ok; move p/ archive é o ÚLTIMO ato mutador)
  const short = git(['rev-parse', '--short', 'HEAD'], root);
  // 1. verify: pendentes (estampa evidência na hora — R.6.1; falha aborta com relato)
  const vTotal = st.verifyPending;
  let vPass = 0;
  if (vTotal) {
    const r = runCli(root, ['verify', spec.id]);
    if (r.code !== 0) {
      process.stderr.write(r.out.endsWith('\n') ? r.out : r.out + '\n');
      die(`close ABORTADO: verify falhou (relato acima). Critérios aprovados mantêm a evidência estampada — corrija e rode o close de novo.`);
    }
    vPass = vTotal;
  }
  // 1b. suíte do projeto 1× (label test do manifesto) — a garantia que dispensa rodar suíte por critério
  // (porte P nunca roda teste até aqui; é ESTE passo que impede arquivar sem nenhum teste ter rodado).
  // Label vazio = capacidade inexistente: N/A reportado no atestado, nunca PASS silencioso nem bloqueio.
  const testCmd = ((manifest(root).commands || {}).test || '').trim();
  let testNote = 'N/A (sem label test)';
  if (testCmd) {
    process.stdout.write(`suite: $ ${testCmd}\n`);
    try { execSync(testCmd, { cwd: root, stdio: 'pipe', timeout: 600000 }); testNote = 'PASS'; }
    catch (e) {
      const detail = truncate(String(e.stdout || '') + String(e.stderr || e.message || ''), 1500);
      process.stderr.write(detail.endsWith('\n') ? detail : detail + '\n');
      die(`close ABORTADO: suíte do projeto falhou (${testCmd}). Corrija e rode o close de novo — nada foi movido.`);
    }
  }
  // 2. digest gerado+MEDIDO (A2) — commit/data finais injetados na extração
  const dgPath = P(spec.dir, 'digest.md');
  if (!exists(dgPath) || digestMeasure(read(dgPath)) > 2000) {
    writeFile(dgPath, genDigest(root, spec, { commitFinal: `\`${short}\``, concluida: now() }));
  }
  const dgBytes = digestMeasure(read(dgPath));
  // 3. (sem rollup automático de feature: tamanho de feature não é gerido no close — rollup é manual via specctl rollup <area>)
  // 4. estampa Commit final (Status/Concluída na cauda compartilhada)
  writeFile(P(spec.dir, 'main.md'), setField(read(P(spec.dir, 'main.md')), 'Commit final', `\`${short}\``));
  // base/branch p/ o menu de finalização (lê o claim ANTES do archive, que o remove)
  const curBranch = currentBranch(root) || '—';
  let baseBranch = '—';
  const cp0 = claimPath(root, spec.id);
  if (exists(cp0)) { const mb = /^\*\*Base:\*\*\s*(.+)$/m.exec(read(cp0)); if (mb) baseBranch = mb[1].trim(); }
  if (baseBranch === '—') baseBranch = detectBaseBranch(root, curBranch);
  // 5-6. move active/→archive/ + índices (reusa a cauda do archive)
  archiveApply(root, spec);
  // 7. lint + audit UMA vez (mata o sweep ritual)
  const { E, W } = runLint(root);
  const AE = [], AW = [];
  auditBase(root, AE, AW);
  // atestado consolidado (≤30 linhas)
  out(`== close ${spec.id} — atestado ==`);
  out(`verify ${vPass}/${vTotal} · suite ${testNote} · digest ${dgBytes}B · lint ${E.length}/${W.length} · audit ${AE.length}/${AW.length}`);
  out(`docs/archive/${spec.id}`);
  if (E.length || AE.length) {
    for (const e of [...E, ...AE].slice(0, 10)) process.stderr.write(`ERRO  ${e.f}: ${e.m}\n`);
    out('ATENÇÃO: lint/audit reportaram erro(s) acima — corrija antes do commit');
    process.exit(1);
  }
  out('nada mais a rodar · commit: git add -A && git commit');
  // menu de FINALIZAÇÃO git — o MODELO pergunta e executa; specctl NUNCA faz merge/push/delete sozinho
  out(`— finalização (o modelo PERGUNTA ao usuário e executa; nada automático) — branch ${curBranch} · base ${baseBranch}`);
  out(`  1. commitar; depois: (a) merge direto em ${baseBranch}  OU  (b) push + abrir PR para ${baseBranch}`);
  out(`  2. voltar (checkout) para ${baseBranch} e git pull?`);
  out(`  3. deletar a branch de trabalho ${curBranch}?`);
}

// ---------------------------------------------------------------- adopt-workspace / entrypoints

function cmdAdoptWorkspace(pos) {
  const root = requireRoot();
  const spec = findSpec(root, pos[0]);
  const pm = parseMain(read(P(spec.dir, 'main.md')));
  const ws = (pm.fields.Workspace || '—').trim();
  if (ws === 'inline') { out('workspace inline — artefatos já vivem na pasta da SPEC, nada a adotar'); process.exit(0); }
  if (!ws || ws === '—') die(`${spec.id} sem **Workspace:** declarado no main.md — nada a adotar (modo external registra ex.: tasks/prd-<slug>/)`);
  const src = path.resolve(root, ws);
  if (!isDir(src)) die(`workspace declarado não existe: ${ws}`);
  let count = 0;
  const skip = new Set(['tmp', 'node_modules', '.git']);
  fs.cpSync(src, spec.dir, {
    recursive: true, force: true,
    filter: (s) => {
      const b = path.basename(s);
      if (skip.has(b)) return false;
      try { if (fs.statSync(s).isFile()) count++; } catch { /* contagem best-effort */ }
      return true;
    },
  });
  appendLog(spec.dir, 'nota', `adopt-workspace: snapshot de ${ws} copiado para a pasta da SPEC (${count} arquivo(s)) — workspace original preservado`);
  out(`adotado: ${count} arquivo(s) de ${ws} → ${relOf(root, spec.dir)} (snapshot pré-archive; o workspace NÃO foi movido)`);
}

function projectName(root) {
  try {
    const pkg = JSON.parse(readSafe(P(root, 'package.json')) || '{}');
    if (pkg.name) return pkg.name;
  } catch { /* sem package.json válido */ }
  return path.basename(root);
}
// Alinhado byte a byte com templates/CLAUDE.md e templates/AGENTS.md (placeholders resolvidos):
// nome preservado do H1 existente, desc/stack preservados no bloco projeto, comandos re-renderizados do manifesto.
function entrypointContent(kind, root, man) {
  const existing = readSafe(P(root, kind));
  const nameM = /^# (?:CLAUDE|AGENTS)\.md — (.+)$/m.exec(existing);
  const name = (nameM && nameM[1].trim()) || projectName(root);
  const cmds = Object.entries(man.commands || {}).filter(([, v]) => v).map(([k, v]) => `- ${k}: \`${v}\``).join('\n')
    || '- (defina os labels em docs/.spec-system.json → commands)';
  const bm = new RegExp(`${escRe(PROJ_INI)}[\\s\\S]*?${escRe(PROJ_FIM)}`).exec(existing);
  const projBlock = bm ? bm[0] : `${PROJ_INI}\n## Projeto\n\n(descreva o projeto em 1-2 frases)\n\n**Stack:** —\n${PROJ_FIM}`;
  const isAgents = kind === 'AGENTS.md';
  const r9 = `**R.9 — 1ª linha de TODA resposta = classificação:** \`[continuidade: SPEC-x]\` (trabalho de SPEC existente) | \`[nova]\` (demanda que muda comportamento/código do produto → exige SPEC) | \`[livre]\` (pergunta, análise, leitura, config de ferramenta, bump de harness — nada que altere o produto; sem SPEC). Ambíguo? PERGUNTE.${isAgents ? '' : ' `/spec` abre os fluxos guiados.'}`;
  const semHooks = isAgents ? `
## Sem hooks? (CLIs sem suporte)

- Início de CADA sessão: rode \`node scripts/specctl.mjs brief\` e cole o output.
- Gatilhos \`/spec\`: "inicie uma spec: <demanda>" · "feche a spec" · "status das specs" · "pause/retome a SPEC-x".
- Antes do PR: \`specctl lint\` e \`audit\`. O CI (docs-gate) é o piso universal.
` : '';
  const labelsNote = `Labels \`test/typecheck/lint/dev/e2e\` espelhados em \`docs/.spec-system.json\` — ${isAgents ? '' : 'hooks, '}CI e \`verify:\` consomem de lá; não hardcode.`;
  return `# ${kind} — ${name}

> Regra dura de posicionamento: este bloco imperativo fica SEMPRE no TOPO, antes de qualquer outra seção. \`specctl entrypoints\` garante isso em regeneração/merge.

## HARD BANS (TIER-0) — valem em TODA resposta

1. **R.6.2** — só o USUÁRIO aceita entrega incompleta, defere ou adia (qualquer "deixar pra depois", em QUALQUER momento) — NUNCA a IA por conta própria. PERGUNTE item a item (implementar agora / SPEC nova / aceitar gap), com citação do usuário.
2. **LOG append-only** — NUNCA editar entradas antigas do \`## LOG\` do journal.md; correção = nova entrada.
3. **\`docs/active/\` VAZIO em \`main\`** — SPEC ativa vive só em branch (CI bloqueia).
4. **Temporários na pasta da SPEC** — \`tmp/\` (descartável) ou \`evidence/\` (persistente); sem SPEC → \`.scratch/\`. Nunca na raiz.
5. **PROIBIDO varrer \`scripts/specctl.mjs\` ou re-ler \`docs/rules/*\` só para "garantir compliance"** — os gates dizem o que falta (\`close <id> --dry\`). Ler a rule DA TAREFA no momento do uso é o caminho certo, não viola este ban.

${r9}
${semHooks}
## Estrutura docs/

- \`docs/RULES.md\` — núcleo do processo (R.1–R.17); detalhe situacional em \`docs/rules/*\`
- \`docs/features/<area>.md\` — memória viva por área · \`docs/INDEX.md\` — mapa (GERADO)
- \`docs/active|future|archive|discard/SPEC-<ts>-<slug>/\` — main.md (contrato) + journal.md (SNAPSHOT + LOG)
- \`docs/claims/\` — trabalho em voo visível em main · \`docs/programs/\` — DAGs de SPECs · \`docs/PROGRAMS.md\` (GERADO) + \`docs/ROADMAP.md\` — o que pegar a seguir (\`specctl next\`) · \`docs/DEFERRED.md\` (GERADO) — deferidos R.6.2
- \`docs/TAXONOMY.md\` — áreas canônicas · \`docs/ARCHITECTURE.md\` — mapa região→feature
- \`docs/CONSTITUTION.md\` — princípios · manifesto: \`docs/.spec-system.json\`

## Comandos

${cmds}

${labelsNote}

## Skills e quando disparar

| Situação | Skill |
|---|---|
| Implementar contra lib/framework/API externa cuja API atual você não domina | **Context7 MCP** — confirme assinatura/versão antes de codar (se indisponível: vendor docs / WebSearch) |
| UI / frontend / estilização | frontend-design (se instalada) |
| Porte G — fase PRD (se pipeline instalado) | cria-prd |
| Fases seguintes (se instalado) | cria-techspec → criar-tasks → executar-task → executar-qa/review/bugfix |

## Mapa de referências — ler SÓ no momento do uso

\`docs/rules/\`: formats (criar/editar artefato) · lifecycle (transições de ciclo de vida) · programs (DAG de SPECs) · interop (workspace externo / pipeline prd) · context (compactação/orçamentos) · retrieval (archive N3) · verification (\`verify:\` e gates) · team (claims/multi-dev/onboarding) · ci (gates de CI).

${projBlock}

---
GERADO por \`specctl entrypoints\` — edite apenas o bloco projeto (entre marcadores).
`;
}
function cmdEntrypoints() {
  const root = requireRoot();
  const man = manifest(root);
  for (const kind of ['CLAUDE.md', 'AGENTS.md']) {
    const content = entrypointContent(kind, root, man);
    writeFile(P(root, kind), content);
    const b = bytesOf(content);
    const max = kind === 'AGENTS.md' ? 6200 : 6000;
    out(`${kind}: ${b} bytes${b > max ? ` — AVISO: acima do orçamento de ${max} (R.16); reduza o bloco projeto` : ''}`);
  }
}

// ---------------------------------------------------------------- hooks (stdin JSON; deny = exit 2)

function readStdinJson() {
  let raw = '';
  try {
    if (process.stdin.isTTY) return null;
    raw = fs.readFileSync(0, 'utf8');
  } catch { return null; }
  if (!raw || !raw.trim()) return null;
  try { return JSON.parse(raw); } catch { return null; }
}
function hookRoot(fp) {
  return findRoot(process.cwd()) || (fp ? findRoot(path.dirname(fp)) : null);
}
function deny(msg) { process.stderr.write(msg + '\n'); process.exit(2); }

function allowlisted(root, actList, targetId) {
  if (!targetId) return false;
  for (const s of actList) {
    const al = readSafe(P(s.dir, '.allow-read'));
    for (const line of al.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)) {
      if (line === targetId || targetId.startsWith(line)) return true;
    }
  }
  return false;
}
function cmdGuardRead() {
  const input = readStdinJson();
  if (!input) process.exit(0);
  const tool = input.tool_name || 'Read';
  if (!['Read', 'Grep', 'Glob'].includes(tool)) process.exit(0);
  const ti = input.tool_input || {};
  // Grep/Glob: porta lateral do R.8 — varrer archive/ ou journal alheio via search dribla o isolamento.
  // Política: path apontando para dentro de archive/ (ou de SPEC não-ativa) = mesma negação do Read.
  // Sem path (busca no repo inteiro) segue livre — o resultado lista paths; a LEITURA deles cai no guard.
  if (tool === 'Grep' || tool === 'Glob') {
    const sp = ti.path;
    if (!sp) process.exit(0);
    const root = hookRoot(sp);
    if (!root) process.exit(0);
    const rel = relOf(root, path.resolve(String(sp)));
    if (rel.startsWith('..') || !rel.startsWith('docs/')) process.exit(0);
    const act = activeSpecs(root);
    const activeIds = new Set(act.map((s) => s.id));
    const tm = /^docs\/(active|future|archive|discard)\/(SPEC-[^/]+)/.exec(rel);
    const targetId = tm ? tm[2] : null;
    if ((rel === 'docs/archive' || rel.startsWith('docs/archive/')) && !allowlisted(root, act, targetId)) {
      deny(`[guard-read] BLOQUEADO (R.8 via ${tool}): busca dentro de docs/archive/ — N3 é acessado via digest/ARCHIVE-INDEX ou subagente (retorno ≤500 tokens).`);
    }
    if (targetId && !activeIds.has(targetId) && tm[1] !== 'archive' && !allowlisted(root, act, targetId)) {
      deny(`[guard-read] BLOQUEADO (R.8 via ${tool}): busca dentro de docs/${tm[1]}/${targetId} — SPEC fora do escopo ativo (main.md/digest.md podem ser LIDOS direto; o resto via subagente ou allowlist).`);
    }
    process.exit(0);
  }
  const fp = ti.file_path;
  if (!fp) process.exit(0);
  const root = hookRoot(fp);
  if (!root) process.exit(0);
  const rel = relOf(root, path.resolve(fp));
  const man = manifest(root);
  // C3 (gated ≥4.1.0) — desarmar a leitura-seguro: não ler o próprio specctl.mjs "pra garantir compliance"
  if (/(^|\/)scripts\/specctl\.mjs$/.test(rel) && revGte(man.template_revision, '4.1.0')) {
    deny(`[guard-read] BLOQUEADO (v4.1): não leia scripts/specctl.mjs para "garantir compliance" — os gates dizem o que falta.\nUse: node scripts/specctl.mjs --help  ·  node scripts/specctl.mjs close <id> --dry`);
  }
  if (rel.startsWith('..') || !rel.startsWith('docs/')) process.exit(0);
  const base = path.basename(rel);
  if (base === 'main.md' || base === 'digest.md') process.exit(0); // sempre livres
  const act = activeSpecs(root);
  const activeIds = new Set(act.map((s) => s.id));
  const tm = /^docs\/(active|future|archive|discard)\/(SPEC-[^/]+)\//.exec(rel);
  const targetId = tm ? tm[2] : null;
  const activeHint = act.length ? act[0].id : '<SPEC-ativa>';
  const exitMsg = (motivo) =>
    `[guard-read] BLOQUEADO (R.8 — isolamento entre SPECs): ${rel}\n` +
    `Motivo: ${motivo}.\n` +
    `Saídas: (1) leia o digest correspondente (digest.md é livre) ou docs/ARCHIVE-INDEX.md; ` +
    `(2) delegue a leitura a um SUBAGENTE e receba um resumo (≤500 tokens); ` +
    `(3) allowlist: adicione a linha '${targetId || '<SPEC-id>'}' em docs/active/${activeHint}/.allow-read.`;
  if (rel.startsWith('docs/archive/')) {
    if (allowlisted(root, act, targetId)) process.exit(0);
    deny(exitMsg('conteúdo de docs/archive/ — N3 é acessado via digest/ARCHIVE-INDEX ou subagente'));
  }
  if (['journal.md', 'state.md', 'memory.md'].includes(base) && targetId && !activeIds.has(targetId)) {
    if (allowlisted(root, act, targetId)) process.exit(0);
    deny(exitMsg(`${base} pertence a SPEC fora do escopo ativo (ativa: ${act.map((s) => s.id).join(', ') || 'nenhuma'})`));
  }
  if (man.policy === 'strict') {
    const freeRoots = ['docs/RULES.md', 'docs/rules/', 'docs/INDEX.md', 'docs/ARCHIVE-INDEX.md', 'docs/TAXONOMY.md', 'docs/ARCHITECTURE.md', 'docs/CONSTITUTION.md', 'docs/BOARD.md', 'docs/claims/', 'docs/programs/', 'docs/.spec-system.json'];
    const isFree = freeRoots.some((r) => rel === r || rel.startsWith(r));
    const isOwnSpec = targetId && activeIds.has(targetId);
    if (!isFree && !isOwnSpec) {
      out(JSON.stringify({ hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'ask', permissionDecisionReason: `policy=strict: leitura N1 de ${rel} exige confirmação do usuário (R.10 estrito). main.md/digest.md são sempre livres.` } }));
      process.exit(0);
    }
  }
  process.exit(0);
}

const TEMP_EXTS = ['.png', '.tmp', '.log'];
const TEMP_PREFIX = /^(dump|trace)/i;
function isTempName(base) { return TEMP_EXTS.includes(path.extname(base).toLowerCase()) || TEMP_PREFIX.test(base); }
function inAllowedTempDir(rel) {
  return rel.includes('/tmp/') || rel.startsWith('tmp/') ||
    rel.includes('/evidence/') || rel.startsWith('evidence/') ||
    rel.includes('/.scratch/') || rel.startsWith('.scratch/') ||
    rel.includes('/intake/');
}
// entradas NOVAS no ## LOG (heading datado com [tipo]) presentes em newText e ausentes em oldText
function newLogHeadings(newText, oldText) {
  const re = /^## \d{4}-\d{2}-\d{2} \d{2}:\d{2} — \[/gm;
  const nt = String(newText), ot = String(oldText), found = [];
  for (const m of nt.matchAll(re)) {
    let end = nt.indexOf('\n', m.index); if (end < 0) end = nt.length;
    const line = nt.slice(m.index, end);
    if (!ot.includes(line)) found.push(line);
  }
  return found;
}
// ---- sinal de contexto (doutrina "quando compactar" de rules/context.md virando sinal — v4.1.1) ----
// Lê o último `usage` do transcript (só o tail, barato) e, quando o contexto REAL cruza o limiar
// da janela, injeta additionalContext sugerindo /compact na PRÓXIMA fronteira de fase. Nunca
// bloqueia; estado por sessão em os.tmpdir re-lembra só a cada +60k de crescimento (buckets).
const CTX_WIN_STD = 200000, CTX_WIN_1M = 1000000;
const CTX_TH_STD = 160000, CTX_TH_1M = 250000, CTX_STEP = 60000;
function ctxLatestTokens(transcriptPath) {
  if (!transcriptPath || typeof transcriptPath !== 'string') return null;
  let fd;
  try { fd = fs.openSync(transcriptPath, 'r'); } catch { return null; }
  try {
    const size = fs.fstatSync(fd).size;
    const start = Math.max(0, size - 256 * 1024);
    const buf = Buffer.alloc(size - start);
    const n = fs.readSync(fd, buf, 0, buf.length, start);
    const lines = buf.toString('utf8', 0, n).split('\n');
    for (let i = lines.length - 1; i >= (start > 0 ? 1 : 0); i--) { // linha 0 de tail truncado = JSON parcial
      const line = lines[i].trim(); if (!line) continue;
      let rec; try { rec = JSON.parse(line); } catch { continue; }
      const u = rec && rec.message && rec.message.usage;
      if (!u || typeof u !== 'object') continue;
      const t = (Number.isFinite(u.input_tokens) ? u.input_tokens : 0)
        + (Number.isFinite(u.cache_read_input_tokens) ? u.cache_read_input_tokens : 0)
        + (Number.isFinite(u.cache_creation_input_tokens) ? u.cache_creation_input_tokens : 0);
      if (t > 0) return { tokens: t, model: rec.message && typeof rec.message.model === 'string' ? rec.message.model : '' };
    }
    return null;
  } catch { return null; } finally { try { fs.closeSync(fd); } catch { /* nunca falha o hook */ } }
}
function maybeSuggestCompact(input, root) {
  try {
    const usage = ctxLatestTokens(input.transcript_path);
    if (!usage) return null;
    // janela: env > manifesto (context_window) > detecção pelo transcript ([1m] no model id ou tokens>200k)
    const envWin = Number.parseInt(process.env.CLAUDE_CODE_AUTO_COMPACT_WINDOW || '', 10);
    const manWin = root ? Number.parseInt(String(manifest(root).context_window || ''), 10) : NaN;
    const win = Number.isInteger(envWin) && envWin > 0 ? envWin
      : Number.isInteger(manWin) && manWin > 0 ? manWin
      : (usage.model.includes('[1m]') || usage.tokens > CTX_WIN_STD) ? CTX_WIN_1M : CTX_WIN_STD;
    const rawTh = process.env.COMPACT_CONTEXT_THRESHOLD;
    const parsedTh = Number.parseInt(rawTh || '', 10);
    if (parsedTh === 0) return null; // COMPACT_CONTEXT_THRESHOLD=0 desliga o sinal
    const th = Number.isInteger(parsedTh) && parsedTh > 0 ? parsedTh : (win >= CTX_WIN_1M ? CTX_TH_1M : CTX_TH_STD);
    if (usage.tokens < th) return null;
    const rawIv = Number.parseInt(process.env.COMPACT_CONTEXT_INTERVAL || '', 10);
    const step = Number.isInteger(rawIv) && rawIv > 0 ? rawIv : CTX_STEP;
    const bucket = Math.floor((usage.tokens - th) / step);
    const sid = String(input.session_id || 'default').replace(/[^a-zA-Z0-9_-]/g, '') || 'default';
    const stateFile = P(os.tmpdir(), `specctl-ctx-${sid}`);
    let last = -1;
    try { const p = parseInt(fs.readFileSync(stateFile, 'utf8').trim(), 10); if (Number.isInteger(p) && p >= 0) last = p; } catch { /* primeiro disparo */ }
    if (bucket <= last) return null;
    try { fs.writeFileSync(stateFile, String(bucket)); } catch { /* sem estado, sem re-lembrete — aceitável */ }
    try { // sweep de estado >14d de outras sessões — nunca falha o hook
      const cut = Date.now() - 14 * 864e5;
      for (const e of fs.readdirSync(os.tmpdir())) {
        if (!e.startsWith('specctl-ctx-') || e === `specctl-ctx-${sid}`) continue;
        const sf = P(os.tmpdir(), e);
        try { if (fs.statSync(sf).mtimeMs < cut) fs.rmSync(sf, { force: true }); } catch { /* ignora */ }
      }
    } catch { /* ignora */ }
    const pct = Math.round((usage.tokens / win) * 100);
    const winLabel = win >= CTX_WIN_1M ? '1M' : `${Math.round(win / 1000)}k`;
    return `[contexto] ~${Math.round(usage.tokens / 1000)}k tokens (${pct}% da janela ${winLabel}) — na PRÓXIMA fronteira de fase: flush do SNAPSHOT/journal e /compact direcionado (tabela "Quando compactar" em docs/rules/context.md). NUNCA no meio de implementação.`;
  } catch { return null; }
}

function cmdGuardWrite() {
  const input = readStdinJson();
  if (!input) process.exit(0);
  const tool = input.tool_name || '';
  if (tool && !['Write', 'Edit', 'MultiEdit'].includes(tool)) process.exit(0);
  const ti = input.tool_input || {};
  const fp = ti.file_path;
  if (!fp) process.exit(0);
  const root = hookRoot(fp);
  if (!root) process.exit(0);
  const rel = relOf(root, path.resolve(fp));
  if (rel.startsWith('..')) process.exit(0);
  const base = path.basename(rel);
  if (['docs/INDEX.md', 'docs/ARCHIVE-INDEX.md', 'docs/PROGRAMS.md', 'docs/DEFERRED.md'].includes(rel)) {
    deny(`[guard-write] BLOQUEADO: ${rel} é GERADO. Caminho correto: edite a fonte (features/TAXONOMY/programs/critérios) e rode: node scripts/specctl.mjs index`);
  }
  if (isTempName(base) && !inAllowedTempDir(rel)) {
    const act = activeSpecs(root);
    const hint = act.length ? `docs/active/${act[0].id}` : 'docs/active/<SPEC>';
    deny(`[guard-write] BLOQUEADO (R.12): '${base}' parece temporário/artefato fora de área permitida. Caminho correto: ${hint}/tmp/ (descartável) ou ${hint}/evidence/ (persistente); sem SPEC ativa: .scratch/.`);
  }
  if (rel.startsWith('docs/active/')) {
    const branch = currentBranch(root);
    if (isProtectedBranch(branch, root)) {
      deny(`[guard-write] BLOQUEADO (R.2): escrita em ${rel} na branch protegida '${branch}'. Caminho correto: crie uma branch (git checkout -b feature/<slug>) e escreva lá; rascunho sem branch vai em docs/future/.`);
    }
  }
  // gates novos SÓ com template_revision ≥ 4.1.0 (repos v4.0 não quebram)
  const gated = revGte(manifest(root).template_revision, '4.1.0');
  const editTexts = () => {
    if (tool === 'Write') return { newText: ti.content || '', oldText: readSafe(path.resolve(fp)) };
    if (tool === 'MultiEdit' && Array.isArray(ti.edits)) return { newText: ti.edits.map((e) => e.new_string || '').join('\n'), oldText: ti.edits.map((e) => e.old_string || '').join('\n') };
    return { newText: ti.new_string || '', oldText: ti.old_string || '' };
  };
  // (3-pre) secret-scan ANTES do write em docs/ (R.15) — o Post (stamp-check) pega o que já está em disco;
  // aqui o segredo é barrado antes de EXISTIR em disco (sessão que morre pós-write não deixa credencial pra trás).
  if (gated && rel.startsWith('docs/')) {
    const { newText, oldText } = editTexts();
    for (const h of scanSecrets(String(newText))) {
      if (String(oldText).includes(h.lineText)) continue; // linha já estava no arquivo: remediação/edição do entorno não é re-negada
      deny(`[guard-write] BLOQUEADO (R.15 — pré-write): SEGREDO (${h.tipo}) no conteúdo destinado a ${rel}. Docs NUNCA guardam segredos — escreva <REDACTED:${h.tipo}> no lugar; se a credencial já vazou em outra via, ROTACIONE.`);
    }
  }
  // (3a) entrada NOVA de LOG via Write/Edit → só via specctl log (Escriba Único); SNAPSHOT/prosa livres
  if (gated && base === 'journal.md') {
    const { newText, oldText } = editTexts();
    const heads = newLogHeadings(newText, oldText);
    if (heads.length) {
      deny(`[guard-write] BLOQUEADO (v4.1 — Escriba Único): entrada nova no ## LOG só via specctl log (a ferramenta carimba NOW+commit+diffstat). Trecho: '${truncate(heads[0], 60)}'.\n` +
        `Caminho correto:\n` +
        `  node scripts/specctl.mjs log <id> <tipo> "título"\n` +
        `  corpo multilinha: acrescente --stdin (heredoc/here-string) ou --body-file <arquivo>\n` +
        `SNAPSHOT e prosa do journal continuam editáveis direto (Edit normal).`);
    }
  }
  // (3b) "verify: exit 0" manual em linha de critério sob docs/active/ (anti-spoofing) → só specctl verify
  if (gated && base === 'main.md' && rel.startsWith('docs/active/')) {
    const { newText, oldText } = editTexts();
    const nt = String(newText), ot = String(oldText);
    const spoofRe = /^\s*-\s*\[[ xX]\][^\n]*verify:\s*exit 0/gm;
    for (const m of nt.matchAll(spoofRe)) {
      let end = nt.indexOf('\n', m.index); if (end < 0) end = nt.length;
      const line = nt.slice(m.index, end);
      if (ot.includes(line)) continue; // já existia: não é escrita nova de evidência
      const sid = (rel.match(/docs\/active\/(SPEC-[^/]+)/) || [])[1] || '<id>';
      deny(`[guard-write] BLOQUEADO (v4.1 anti-spoofing): só specctl verify grava evidência "verify: exit 0" em critério — a ferramenta roda o comando e carimba na hora. Trecho: '${truncate(line, 60)}'.\n` +
        `Caminho correto: node scripts/specctl.mjs verify ${sid}  (critério manual, sem comando: node scripts/specctl.mjs check ${sid} <n> --evidence "...").`);
    }
  }
  if (base === 'journal.md' && tool !== 'Write') {
    const olds = tool === 'MultiEdit' && Array.isArray(ti.edits) ? ti.edits.map((e) => e.old_string || '') : [ti.old_string || ''];
    const txt = readSafe(path.resolve(fp));
    if (txt) {
      const logIdx = txt.indexOf('## LOG');
      if (logIdx >= 0) {
        // checagem POR POSIÇÃO: nega qualquer old_string que comece dentro da região do LOG
        // anterior à última entrada (cobre fragmentos de heading e corpos de entradas antigas).
        // A última entrada e o SNAPSHOT permanecem editáveis.
        const headRe = /^## \d{4}-\d{2}-\d{2} \d{2}:\d{2} — .*$/gm;
        let lastIdx = -1;
        let m;
        while ((m = headRe.exec(txt)) !== null) { if (m.index > logIdx) lastIdx = m.index; }
        if (lastIdx >= 0) {
          for (const oldS of olds) {
            if (!oldS) continue;
            const posOld = txt.indexOf(oldS);
            if (posOld < 0) continue; // old_string inexistente no arquivo: não nega — o Edit falha sozinho
            if (posOld > logIdx && posOld < lastIdx) {
              deny(`[guard-write] BLOQUEADO (TIER-0): o LOG do journal é append-only — proibido editar entradas antigas (trecho '${truncate(oldS, 60)}' está antes da última entrada do LOG). Caminho correto: adicione uma NOVA entrada '## ${now()} — [tipo] ...' ao FINAL do arquivo (o SNAPSHOT e a última entrada podem ser editados).`);
            }
          }
        }
      }
    }
  }
  // sinal de contexto (não-bloqueante) — só depois de TODOS os gates permitirem a escrita
  if (gated) {
    const sug = maybeSuggestCompact(input, root);
    if (sug) out(JSON.stringify({ hookSpecificOutput: { hookEventName: 'PreToolUse', additionalContext: sug } }));
  }
  process.exit(0);
}

function cmdStampCheck() {
  const input = readStdinJson();
  if (!input) process.exit(0);
  const ti = input.tool_input || {};
  const fp = ti.file_path;
  if (!fp || !exists(fp)) process.exit(0);
  const abs = path.resolve(fp);
  const root = hookRoot(fp);
  const rel = root ? relOf(root, abs) : path.basename(abs);
  let buf;
  try { buf = fs.readFileSync(abs); } catch { process.exit(0); }
  if (buf.length > 2 * 1024 * 1024 || buf.includes(0)) process.exit(0); // binário/grande: ignora
  let txt = buf.toString('utf8');
  // 1) resolve {{NOW}} — só em docs/ e entrypoints (não corromper templates de código do projeto)
  const eligible = root && (rel.startsWith('docs/') || ['CLAUDE.md', 'AGENTS.md'].includes(rel));
  if (eligible && txt.includes('{{NOW}}')) {
    txt = txt.split('{{NOW}}').join(now());
    writeFile(abs, txt);
    out(`[stamp-check] {{NOW}} resolvido para ${now()} em ${rel}`);
  }
  // 2) timestamps novos ±24h (warn stdout)
  const underDocs = !!root && rel.startsWith('docs/');
  let newText = '';
  if (typeof ti.new_string === 'string') newText = ti.new_string;
  else if (Array.isArray(ti.edits)) newText = ti.edits.map((e) => e.new_string || '').join('\n');
  // Write sob docs/: valida o content COMPLETO (timestamps inventados no início também contam — R.6)
  else if (typeof ti.content === 'string') newText = underDocs ? ti.content : ti.content.split(/\r?\n/).slice(-40).join('\n');
  else if (underDocs) newText = txt; // Write sob docs/ sem content no payload: valida o arquivo inteiro
  const oldText = typeof ti.old_string === 'string' ? ti.old_string : (Array.isArray(ti.edits) ? ti.edits.map((e) => e.old_string || '').join('\n') : '');
  const drift = [];
  for (const m of newText.matchAll(/\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}\b/g)) {
    if (oldText.includes(m[0]) || drift.includes(m[0])) continue;
    const t = parseTs(m[0]);
    if (t && Math.abs(t.getTime() - Date.now()) > 24 * 3600 * 1000) drift.push(m[0]);
  }
  if (drift.length) out(`[stamp-check] AVISO (R.6): timestamp(s) fora de ±24h do relógio (NOW=${now()}): ${drift.slice(0, 3).join(', ')} — use {{NOW}} ou o NOW injetado, nunca invente data.`);
  // 3) secret-scan no arquivo tocado (deny-feedback = exit 2)
  const hits = scanSecrets(txt);
  if (hits.length) {
    const h = hits[0];
    deny(`[stamp-check] SEGREDO detectado (${h.tipo}, linha ${h.line}) em ${rel}. R.15: docs NUNCA guardam segredos — substitua AGORA por <REDACTED:${h.tipo}> e ROTACIONE a credencial exposta (exceção auditada ao append-only cobre a remediação).`);
  }
  process.exit(0);
}

function cmdSessionClose() {
  const input = readStdinJson();
  if (input && input.stop_hook_active) process.exit(0); // avisa UMA vez
  const root = findRoot(process.cwd());
  if (!root) process.exit(0);
  const act = activeSpecs(root);
  if (!act.length) process.exit(0);
  // spawnSync direto: o stdout NÃO pode ser trimado (o 1º caractere de status pode ser espaço)
  const st = spawnSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' });
  if (st.error || st.status !== 0) {
    process.stderr.write(`[session-close] AVISO: git status falhou: ${(st.stderr || (st.error && st.error.message) || '').trim()} — verificação de journal pulada\n`);
    process.exit(0);
  }
  const changed = (st.stdout || '').split('\n').filter((l) => l.trim()).map((l) => {
    let p = l.slice(3).trim();
    if (p.includes(' -> ')) p = p.split(' -> ')[1];
    return p.replace(/^"|"$/g, '');
  });
  const codeChanged = changed.some((p) => !p.startsWith('docs/') && !p.startsWith('.scratch/') && !p.startsWith('.claude/'));
  const journalChanged = act.some((s) => changed.includes(`docs/active/${s.id}/journal.md`));
  if (codeChanged && !journalChanged) {
    out(JSON.stringify({
      decision: 'block',
      reason: `Código alterado nesta sessão sem atualização do journal da SPEC ativa (R.6.1). Antes de encerrar: sobrescreva o SNAPSHOT e adicione uma entrada datada ao LOG em docs/active/${act[0].id}/journal.md — ou registre por que não se aplica.`,
    }));
  }
  process.exit(0);
}

// ---------------------------------------------------------------- self-test

const SELF = path.resolve(process.argv[1]);
function runCli(cwd, args, input) {
  const r = spawnSync(process.execPath, [SELF, ...args], { cwd, encoding: 'utf8', input });
  return { code: r.status === null ? -1 : r.status, out: (r.stdout || '') + (r.stderr || '') };
}
function stManifest() {
  return JSON.stringify({
    schema: SCHEMA, template_revision: VERSION, installed_at: '2026-01-01 10:00',
    policy: 'standard', interop: 'none', product: null,
    commands: { test: '', typecheck: '', lint: '', dev: '', e2e: '' },
  }, null, 2) + '\n';
}
function stBase(tmp, name) {
  const root = P(tmp, name);
  for (const d of ['features', 'active', 'future', 'archive', 'discard', 'claims', 'programs']) {
    fs.mkdirSync(P(root, 'docs', d), { recursive: true });
  }
  fs.mkdirSync(P(root, '.scratch'), { recursive: true });
  writeFile(P(root, 'docs', '.spec-system.json'), stManifest());
  writeFile(P(root, 'docs', 'TAXONOMY.md'), '# TAXONOMY\n\n- core — núcleo do sistema (aliases proibidos: nucleo→core)\n');
  writeFile(P(root, 'docs', 'RULES.md'), '# RULES (fixture)\n\nNúcleo mínimo para self-test.\n');
  const g = gitRun(['init', '-q'], root);
  if (!g.ok) process.stderr.write(`[self-test] AVISO: git init falhou (${g.err}) — fixtures seguem sem git\n`);
  return root;
}
function stFeatureCore(concludedPrefix, extraLine = '') {
  return `# Feature: core

**Keywords:** núcleo, base
**Arquivos principais:**
  - src/core.ts
**Resumo:** Núcleo do sistema de exemplo do self-test.
${extraLine}
## Specs desta feature

### Concluídas

${concludedPrefix ? `- ${concludedPrefix}-exemplo-arquivada | 2026-01-12 | \`abc1234\` | Exemplo` : ''}

### Planejadas (future/)

## Estado atual

Estado inicial de exemplo.

## Decisões arquiteturais ativas

- **DEC-20260110-1000-exemplo** (ativa) — decisão de exemplo.

## Alternativas consideradas e rejeitadas

## Gotchas

## Estado congelado (se houver)
`;
}
function stMain(idTs, o = {}) {
  const crits = o.criterios || ['- [ ] critério pendente | verify: `node -e "process.exit(0)"`'];
  return `# SPEC-${idTs}: exemplo

**Status:** ${o.status || 'active'}
**Porte:** ${o.porte || 'M'}
**Owner:** ${o.owner || '@tester'}
**Criada:** ${o.criada || '2026-01-10 10:00'}
**Ativada:** ${o.ativada || '2026-01-10 10:05'}
**Concluída:** ${o.concluida || '—'}
**Pausada em:** ${o.pausada || '—'}
**Commit final:** ${o.commitFinal || '—'}
**Keywords:** exemplo
**Features:** ${o.features || 'core'}
**Branch:** ${o.branch || '—'}
**Programa:** —
**Workspace:** —
**Origem:** self-test
**Resumo:** SPEC de exemplo do self-test.

## Objetivo

Exercitar o lint.

## Escopo

**DENTRO:**
- exemplo

**FORA:**
- resto

## Implementação

Trivial.

## Critério de aceite

${crits.join('\n')}
${o.extra || ''}`;
}
function stJournal(idTs, { conclusao = false, snapshotDone = false } = {}) {
  let j = makeJournal(idTs, '2026-01-10 10:05');
  // snapshotDone: simula um SNAPSHOT sobrescrito (SPEC pronta para fechar) — sem placeholders do template
  if (snapshotDone) j = j.replace('início — nada feito ainda', 'feature entregue').replace('<primeiro passo concreto>', '—').replace('<fase>', 'impl');
  j += '\n## 2026-01-10 10:05 — [ativação] SPEC ativada\n';
  if (conclusao) j += '\n## 2026-01-12 12:00 — [conclusão] Entregue\n';
  return j;
}
const ST_ARCH = '20260110-1000';
const ST_ACT = '20260601-0900';
function stArchiveSpec(root, { digest = 'ok', criterios, journal } = {}) {
  const id = `SPEC-${ST_ARCH}-exemplo-arquivada`;
  const dir = P(root, 'docs', 'archive', id);
  writeFile(P(dir, 'main.md'), stMain(ST_ARCH, {
    status: 'done', concluida: '2026-01-12 12:00', commitFinal: '`abc1234`',
    criterios: criterios || ['- [x] Funciona de ponta a ponta (2026-01-12 11:50, commit `abc1234`, verify: exit 0)'],
  }));
  writeFile(P(dir, 'journal.md'), journal || stJournal(ST_ARCH, { conclusao: true }));
  if (digest === 'ok') writeFile(P(dir, 'digest.md'), '# Digest\n\nObjetivo: exemplo. Entregue: núcleo. Decisões: nenhuma. Gotchas: nenhum.\nCommits: `abc1234`.\n');
  else if (digest === 'big') writeFile(P(dir, 'digest.md'), '# Digest\n\n' + 'x'.repeat(2100) + '\n');
  return id;
}
function stActiveSpec(root, { criterios, porte } = {}) {
  const id = `SPEC-${ST_ACT}-exemplo-ativa`;
  const dir = P(root, 'docs', 'active', id);
  writeFile(P(dir, 'main.md'), stMain(ST_ACT, { status: 'active', criterios, porte }));
  writeFile(P(dir, 'journal.md'), stJournal(ST_ACT));
  writeFile(P(root, 'docs', 'claims', `${id}.md`), makeClaim({ id, title: 'exemplo', owner: '@tester', branch: 'feature/x', features: 'core', ativada: '2026-01-10 10:05' }));
  return id;
}
// commit de fixture (identidade local, sem gpg/hooks) — retorna false se git indisponível
function stGitCommit(root) {
  if (!isDir(P(root, '.git'))) return false;
  gitRun(['config', 'user.email', 'selftest@example.com'], root);
  gitRun(['config', 'user.name', 'selftest'], root);
  if (!gitRun(['add', '-A'], root).ok) return false;
  return gitRun(['-c', 'commit.gpgsign=false', 'commit', '-q', '--no-verify', '-m', 'fixture'], root).ok;
}
// branch de feature (não-main) p/ exercitar guards sob docs/active/ sem esbarrar em R.2
function stFeatureBranch(root) {
  if (!isDir(P(root, '.git'))) return false;
  return gitRun(['checkout', '-q', '-b', 'feature/x'], root).ok;
}
// manifesto v4.0.0: os denies novos (LOG-append, verify-spoof, guard-read specctl) ficam DESATIVADOS
function stManifest40(root) {
  writeFile(P(root, 'docs', '.spec-system.json'), JSON.stringify({
    schema: SCHEMA, template_revision: '4.0.0', installed_at: '2026-01-01 10:00',
    policy: 'standard', interop: 'none', product: null,
    commands: { test: '', typecheck: '', lint: '', dev: '', e2e: '' },
  }, null, 2) + '\n');
}
// SPEC ativa com id arbitrário (várias na mesma fixture) — main+journal+claim
function stActiveSpecId(root, idTs, slug, o = {}) {
  const id = `SPEC-${idTs}-${slug}`;
  const dir = P(root, 'docs', 'active', id);
  writeFile(P(dir, 'main.md'), stMain(idTs, { status: 'active', ...o }));
  writeFile(P(dir, 'journal.md'), o.journal || stJournal(idTs));
  writeFile(P(root, 'docs', 'claims', `${id}.md`), makeClaim({ id, title: slug, owner: '@tester', branch: 'feature/x', features: o.features || 'core', ativada: '2026-01-10 10:05' }));
  return id;
}

function cmdSelfTest() {
  const tmp = P(os.tmpdir(), `specctl-selftest-${crypto.randomBytes(4).toString('hex')}`);
  fs.mkdirSync(tmp, { recursive: true });
  const results = [];
  const fixture = (name, fn) => {
    try { fn(); results.push([name, true, '']); }
    catch (e) { results.push([name, false, e.message]); }
  };
  const expect = (cond, msg) => { if (!cond) throw new Error(msg); };
  const expectRun = (r, code, substr, label) => {
    expect(r.code === code, `${label}: exit ${r.code} (esperado ${code}) — saída: ${truncate(r.out, 400)}`);
    if (substr) expect(r.out.includes(substr), `${label}: saída sem "${substr}" — saída: ${truncate(r.out, 400)}`);
  };

  fixture('valido', () => {
    const root = stBase(tmp, 'valido');
    stArchiveSpec(root);
    stActiveSpec(root);
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(`SPEC-${ST_ARCH}`));
    expectRun(runCli(root, ['index']), 0, null, 'index');
    expectRun(runCli(root, ['lint']), 0, null, 'lint');
  });
  fixture('checkbox-sem-timestamp', () => {
    const root = stBase(tmp, 'cb-sem-ts');
    stActiveSpec(root, { criterios: ['- [x] Feito sem carimbo'] });
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    expectRun(runCli(root, ['lint']), 1, 'sem timestamp', 'lint');
  });
  fixture('future-malformada', () => {
    const root = stBase(tmp, 'future-mal');
    const id = 'SPEC-20260501-1200-rascunho';
    writeFile(P(root, 'docs', 'future', id, 'main.md'), stMain('20260501-1200', { status: 'active' }));
    expectRun(runCli(root, ['lint']), 1, 'coerência pasta↔status', 'lint');
  });
  fixture('archive-criterio-aberto', () => {
    const root = stBase(tmp, 'arch-aberto');
    stArchiveSpec(root, {
      criterios: [
        '- [x] Feito (2026-01-12 11:50, commit `abc1234`, verify: exit 0)',
        '- [ ] Ficou de fora sem aceite',
      ],
    });
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(`SPEC-${ST_ARCH}`));
    expectRun(runCli(root, ['lint']), 1, 'aceito-incompleto', 'lint');
  });
  fixture('archive-sem-digest', () => {
    const root = stBase(tmp, 'arch-sem-digest');
    stArchiveSpec(root, { digest: 'none' });
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(`SPEC-${ST_ARCH}`));
    expectRun(runCli(root, ['lint']), 1, 'digest.md', 'lint');
  });
  fixture('discard-legitimo', () => {
    const root = stBase(tmp, 'discard-ok');
    const id = 'SPEC-20260301-1500-abandonada';
    const dir = P(root, 'docs', 'discard', id);
    writeFile(P(dir, 'main.md'), stMain('20260301-1500', {
      status: 'discarded', criterios: ['- [ ] não implementado'],
      extra: '\n## Justificativa de descarte\n\nAbordagem substituída por lib pronta (2026-03-02 09:00).\n',
    }));
    writeFile(P(dir, 'journal.md'), stJournal('20260301-1500', { conclusao: true }));
    writeFile(P(dir, 'digest.md'), '# Digest\n\nDescartada: lib pronta cobre o caso. Lição: pesquisar antes.\n');
    expectRun(runCli(root, ['lint']), 0, null, 'lint');
  });
  fixture('segredo-plantado', () => {
    const root = stBase(tmp, 'segredo');
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore('', 'chave usada: AKIAABCDEFGHIJKLMNOP\n'));
    expectRun(runCli(root, ['lint']), 1, 'segredo detectado', 'lint');
  });
  fixture('deps-ciclicas', () => {
    const root = stBase(tmp, 'deps-ciclo');
    const a = 'SPEC-20260401-1000-no-a';
    const b = 'SPEC-20260401-1100-no-b';
    writeFile(P(root, 'docs', 'future', a, 'main.md'), stMain('20260401-1000', { status: 'draft', ativada: '—' }));
    writeFile(P(root, 'docs', 'future', b, 'main.md'), stMain('20260401-1100', { status: 'draft', ativada: '—' }));
    writeFile(P(root, 'docs', 'programs', 'alpha.md'), `# Programa: alpha\n\n**Owner:** @tester\n\n- ${a} | depende de: ${b}\n- ${b} | depende de: ${a}\n`);
    expectRun(runCli(root, ['audit', '--deps']), 1, 'ciclo', 'audit --deps');
  });
  fixture('budget-estourado', () => {
    const root = stBase(tmp, 'budget');
    stArchiveSpec(root, { digest: 'big' });
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(`SPEC-${ST_ARCH}`));
    expectRun(runCli(root, ['lint']), 1, 'orçamento excedido', 'lint');
  });
  fixture('guard-read-nega', () => {
    const root = stBase(tmp, 'guard-read');
    stActiveSpec(root);
    const bid = 'SPEC-20260201-0800-pausada';
    writeFile(P(root, 'docs', 'future', bid, 'main.md'), stMain('20260201-0800', { status: 'paused', pausada: '2026-02-02 10:00 — aguardando API' }));
    writeFile(P(root, 'docs', 'future', bid, 'journal.md'), stJournal('20260201-0800'));
    const payload = JSON.stringify({ tool_name: 'Read', tool_input: { file_path: P(root, 'docs', 'future', bid, 'journal.md') } });
    expectRun(runCli(root, ['guard-read'], payload), 2, 'R.8', 'guard-read deny');
  });
  fixture('guard-read-allowlist', () => {
    const root = stBase(tmp, 'guard-allow');
    const aid = stActiveSpec(root);
    const bid = 'SPEC-20260201-0800-pausada';
    writeFile(P(root, 'docs', 'future', bid, 'main.md'), stMain('20260201-0800', { status: 'paused', pausada: '2026-02-02 10:00 — aguardando API' }));
    writeFile(P(root, 'docs', 'future', bid, 'journal.md'), stJournal('20260201-0800'));
    writeFile(P(root, 'docs', 'active', aid, '.allow-read'), bid + '\n');
    const payload = JSON.stringify({ tool_name: 'Read', tool_input: { file_path: P(root, 'docs', 'future', bid, 'journal.md') } });
    expectRun(runCli(root, ['guard-read'], payload), 0, null, 'guard-read allowlist');
  });
  fixture('guard-write-index-gerado', () => {
    const root = stBase(tmp, 'guard-idx');
    const payload = JSON.stringify({ tool_name: 'Write', tool_input: { file_path: P(root, 'docs', 'INDEX.md'), content: 'x' } });
    expectRun(runCli(root, ['guard-write'], payload), 2, 'specctl.mjs index', 'guard-write INDEX');
  });
  fixture('guard-write-temporario', () => {
    const root = stBase(tmp, 'guard-tmp');
    const payload = JSON.stringify({ tool_name: 'Write', tool_input: { file_path: P(root, 'saida.log'), content: 'log' } });
    expectRun(runCli(root, ['guard-write'], payload), 2, 'tmp/', 'guard-write temp');
  });
  fixture('guard-write-suggest-compact', () => {
    const root = stBase(tmp, 'guard-ctx');
    const sid = `st-${crypto.randomBytes(4).toString('hex')}`;
    const tp = P(tmp, `transcript-${sid}.jsonl`);
    writeFile(tp, JSON.stringify({ message: { model: 'claude-opus-4-8', usage: { input_tokens: 150000, cache_read_input_tokens: 25000, cache_creation_input_tokens: 1000 } } }) + '\n');
    const payload = JSON.stringify({ tool_name: 'Write', tool_input: { file_path: P(root, 'docs', 'nota.md'), content: 'oi' }, transcript_path: tp, session_id: sid });
    const r = runCli(root, ['guard-write'], payload);
    expectRun(r, 0, 'additionalContext', 'guard-write sugere compact acima do limiar');
    expect(r.out.includes('[contexto]'), 'guard-write: mensagem [contexto] ausente');
    const r2 = runCli(root, ['guard-write'], payload);
    expectRun(r2, 0, null, 'guard-write mesmo bucket');
    expect(!r2.out.includes('additionalContext'), 'guard-write: re-sugeriu no MESMO bucket (estado por sessão falhou)');
    // manifesto com context_window=1M: 176k < 250k (limiar 1M) → silêncio, mesmo sem marcador [1m]
    const manFp = P(root, 'docs', '.spec-system.json');
    const man = JSON.parse(read(manFp));
    man.context_window = 1000000;
    writeFile(manFp, JSON.stringify(man, null, 2));
    const sid3 = `st-${crypto.randomBytes(4).toString('hex')}`;
    const payload3 = JSON.stringify({ tool_name: 'Write', tool_input: { file_path: P(root, 'docs', 'nota.md'), content: 'oi' }, transcript_path: tp, session_id: sid3 });
    const r3 = runCli(root, ['guard-write'], payload3);
    expectRun(r3, 0, null, 'guard-write janela do manifesto');
    expect(!r3.out.includes('additionalContext'), 'guard-write: ignorou context_window do manifesto (sugeriu a 176k numa janela 1M)');
  });
  fixture('stamp-check-now', () => {
    const root = stBase(tmp, 'stamp');
    const fp = P(root, 'docs', 'nota.md');
    writeFile(fp, 'Atualizado: {{NOW}}\n');
    const payload = JSON.stringify({ tool_name: 'Write', tool_input: { file_path: fp, content: 'Atualizado: {{NOW}}\n' } });
    expectRun(runCli(root, ['stamp-check'], payload), 0, null, 'stamp-check');
    expect(!read(fp).includes('{{NOW}}'), 'stamp-check: {{NOW}} não foi substituído');
    expect(TS_RE.test(read(fp)), 'stamp-check: timestamp ausente após substituição');
  });
  fixture('next-programa', () => {
    const root = stBase(tmp, 'next-prog');
    // nó raiz done (arquivado), nó pronto (draft, dep done) e nó bloqueado (draft, dep no nó pronto)
    const raiz = 'SPEC-20260401-0900-no-raiz';
    const pronto = 'SPEC-20260401-1000-no-pronto';
    const blk = 'SPEC-20260401-1100-no-bloqueado';
    writeFile(P(root, 'docs', 'archive', raiz, 'main.md'), stMain('20260401-0900', { status: 'done', concluida: '2026-04-02 10:00', commitFinal: '`abc1234`' }));
    writeFile(P(root, 'docs', 'archive', raiz, 'journal.md'), stJournal('20260401-0900', { conclusao: true }));
    writeFile(P(root, 'docs', 'archive', raiz, 'digest.md'), '# Digest\n\nRaiz concluída.\n');
    writeFile(P(root, 'docs', 'future', pronto, 'main.md'), stMain('20260401-1000', { status: 'draft', ativada: '—' }));
    writeFile(P(root, 'docs', 'future', blk, 'main.md'), stMain('20260401-1100', { status: 'draft', ativada: '—' }));
    writeFile(P(root, 'docs', 'programs', 'demo.md'), `# Programa: demo\n\n**Owner:** @tester\n\n- ${pronto} | depende de: ${raiz}\n- ${blk} | depende de: ${pronto}\n`);
    const r = runCli(root, ['next']);
    expectRun(r, 0, '▶ pronto', 'next');
    expect(r.out.includes(pronto), `next: nó pronto ausente — saída: ${truncate(r.out, 400)}`);
    expect(r.out.includes('🔒') && r.out.includes(blk), `next: nó bloqueado ausente — saída: ${truncate(r.out, 400)}`);
    expect(r.out.includes(`aguarda ${pronto}`), `next: motivo do bloqueio ausente — saída: ${truncate(r.out, 400)}`);
  });
  fixture('next-roadmap', () => {
    const root = stBase(tmp, 'next-roadmap');
    const r1 = 'SPEC-20260501-1000-avulsa-um';
    const r2 = 'SPEC-20260502-1000-avulsa-dois';
    writeFile(P(root, 'docs', 'future', r1, 'main.md'), stMain('20260501-1000', { status: 'draft', ativada: '—' }));
    writeFile(P(root, 'docs', 'future', r2, 'main.md'), stMain('20260502-1000', { status: 'draft', ativada: '—' }));
    writeFile(P(root, 'docs', 'ROADMAP.md'), `# ROADMAP\n\n1. ${r1}\n2. ${r2}\n`);
    const r = runCli(root, ['next']);
    expectRun(r, 0, 'ROADMAP', 'next');
    expect(r.out.includes(`▶ próximo:  ${r1}`), `next: topo do roadmap ausente — saída: ${truncate(r.out, 400)}`);
    expect(r.out.includes('· depois:') && r.out.includes(r2), `next: "depois" do roadmap ausente — saída: ${truncate(r.out, 400)}`);
  });
  fixture('programs-index', () => {
    const root = stBase(tmp, 'prog-index');
    const raiz = 'SPEC-20260601-0900-idx-raiz';
    const filho = 'SPEC-20260601-1000-idx-filho';
    const feito = 'SPEC-20260601-0800-idx-feito';
    writeFile(P(root, 'docs', 'archive', feito, 'main.md'), stMain('20260601-0800', { status: 'done' }));
    writeFile(P(root, 'docs', 'future', raiz, 'main.md'), stMain('20260601-0900', { status: 'draft', ativada: '—' }));
    writeFile(P(root, 'docs', 'future', filho, 'main.md'), stMain('20260601-1000', { status: 'draft', ativada: '—' }));
    writeFile(P(root, 'docs', 'programs', 'demo.md'), `# Programa: demo\n\n**Owner:** @tester\n\n- ${feito} | depende de: —\n- ${raiz} | depende de: —\n- ${filho} | depende de: ${raiz}\n`);
    expectRun(runCli(root, ['index']), 0, 'PROGRAMS.md', 'index');
    const p = P(root, 'docs', 'PROGRAMS.md');
    expect(exists(p), 'programs-index: docs/PROGRAMS.md não foi gerado');
    const first = read(p);
    expect(first.includes(GERADO_MARK), 'programs-index: marcador GERADO ausente');
    expect(first.includes('## demo — aberto · 1/3 · owner @tester'), `programs-index: cabeçalho do bloco incorreto — saída: ${truncate(first, 400)}`);
    expect(first.includes(`- prontos: ${raiz}`), `programs-index: linha "prontos" ausente — saída: ${truncate(first, 400)}`);
    expect(first.includes(`- bloqueados: ${filho} (aguarda ${raiz})`), `programs-index: linha "bloqueados" ausente — saída: ${truncate(first, 400)}`);
    expect(first.includes(`- concluídos: ${feito}`), `programs-index: linha "concluídos" ausente — saída: ${truncate(first, 400)}`);
    runCli(root, ['index']); // regenera
    expect(read(p) === first, 'programs-index: regeneração NÃO é idempotente (diff no PROGRAMS.md)');
    // nó PAUSADO aparece na linha própria (visível, não pegável) — e no next com ⏸
    const pausado = 'SPEC-20260601-1100-idx-pausado';
    writeFile(P(root, 'docs', 'future', pausado, 'main.md'), stMain('20260601-1100', { status: 'paused', pausada: '2026-06-02 09:00 — aguardando API' }));
    writeFile(P(root, 'docs', 'future', pausado, 'journal.md'), stJournal('20260601-1100'));
    writeFile(P(root, 'docs', 'programs', 'demo.md'), `# Programa: demo\n\n**Owner:** @tester\n\n- ${feito} | depende de: —\n- ${raiz} | depende de: —\n- ${filho} | depende de: ${raiz}\n- ${pausado} | depende de: —\n`);
    expectRun(runCli(root, ['index']), 0, null, 'index com pausado');
    const second = read(p);
    expect(second.includes(`- pausados: ${pausado} (retomar: specctl resume)`), `programs-index: linha "pausados" ausente — saída: ${truncate(second, 400)}`);
    const rn = runCli(root, ['next']);
    expect(rn.out.includes('⏸ pausado') && rn.out.includes(pausado), `next: nó pausado ausente — saída: ${truncate(rn.out, 400)}`);
  });
  fixture('log-scribe', () => {
    const root = stBase(tmp, 'log-scribe');
    const id = stActiveSpec(root);
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    expect(stGitCommit(root), 'git commit indisponível na fixture');
    const bad = runCli(root, ['log', id, 'tipoerrado', 'x']);
    expectRun(bad, 1, 'tipo inválido', 'log tipo inválido');
    expect(bad.out.includes(LOG_TYPES.join(' | ')), `gramática completa ausente no erro — saída: ${truncate(bad.out, 300)}`);
    expect(bad.out.includes('PowerShell') && bad.out.includes('EOF'), 'erro sem exemplos heredoc/here-string');
    const multi = runCli(root, ['log', id, 'nota', 'linha1\nlinha2']);
    expectRun(multi, 1, 'single-line', 'log título multilinha');
    const r = runCli(root, ['log', id, 'decisão', 'Optamos por X', '--stdin'], 'porque Y\r\nlinha dois\n');
    expectRun(r, 0, '[decisão] Optamos por X', 'log grava');
    expect(r.out.includes('porque Y'), `eco do corpo ausente — saída: ${truncate(r.out, 300)}`);
    expect(r.out.trim().split('\n').length <= 2, `eco acima de 2 linhas — saída: ${truncate(r.out, 300)}`);
    const j = norm(read(P(root, 'docs', 'active', id, 'journal.md')));
    expect(/— \[decisão\] Optamos por X\n\nporque Y\nlinha dois\n⎿ commit [0-9a-f]+/.test(j), `entrada/rodapé fora do formato — fim do journal: ${truncate(j.slice(-260), 260)}`);
    expect(!j.includes('\r'), 'CRLF não normalizado no corpo');
  });
  fixture('check-estampa', () => {
    const root = stBase(tmp, 'check');
    const id = stActiveSpec(root, {
      criterios: [
        '- [ ] validado manualmente com o usuário',
        '- [ ] roda ponta a ponta | verify: `node -e "process.exit(0)"`',
      ],
    });
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    expect(stGitCommit(root), 'git commit indisponível na fixture');
    const rec = runCli(root, ['check', id, '2']);
    expectRun(rec, 1, 'rota: node scripts/specctl.mjs verify', 'check recusa critério com verify:');
    const r = runCli(root, ['check', id, '1', '--evidence', 'aprovado pelo usuário']);
    expectRun(r, 0, '[x] validado manualmente', 'check estampa');
    const line = norm(read(P(root, 'docs', 'active', id, 'main.md'))).split('\n').find((l) => l.includes('validado manualmente'));
    expect(/^- \[x\] validado manualmente com o usuário \(\d{4}-\d{2}-\d{2} \d{2}:\d{2}, commit `[0-9a-f]+`, evidence: aprovado pelo usuário\)$/.test(line), `estampa incorreta: ${line}`);
    expect(!line.includes('verify:'), 'check escreveu o token verify:');
  });
  fixture('digest-gera-e-cap', () => {
    const root = stBase(tmp, 'digest');
    const id = stActiveSpec(root);
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    const r = runCli(root, ['digest', id]);
    expectRun(r, 0, '# Digest — SPEC-', 'digest gera');
    const dg = P(root, 'docs', 'active', id, 'digest.md');
    expect(exists(dg), 'digest.md não gravado');
    expect(digestMeasure(read(dg)) <= 2000, `digest acima de 2000B (LF, HTML descontado): ${digestMeasure(read(dg))}`);
    expect(read(dg).includes(DIGEST_STUB_NOTE), 'stub auto-doc do cap ausente no digest gerado');
    const big = runCli(root, ['digest', id, '--stdin'], '# Digest\n\n' + 'x'.repeat(2100) + '\n');
    expectRun(big, 1, 'corte ~', 'digest --stdin acima do cap');
    expect(/\d+B > 2000B/.test(big.out), `mensagem acionável ausente — saída: ${truncate(big.out, 300)}`);
    const ok = runCli(root, ['digest', id, '--stdin'], '# Digest\n\nresumo curto refinado.\n');
    expectRun(ok, 0, 'digest gravado', 'digest --stdin dentro do cap');
    expect(read(dg).includes('refinado'), 'digest --stdin não sobrescreveu');
  });
  fixture('rollup-orcamento', () => {
    const root = stBase(tmp, 'rollup');
    const filler = 'linha de contexto acumulado que ocupa espaço no arquivo da feature. '.repeat(11);
    let deltas = '';
    for (let i = 1; i <= 12; i++) deltas += `- SPEC-202601${String(i).padStart(2, '0')}-1000 — delta ${i}: ${filler}\n`;
    writeFile(P(root, 'docs', 'features', 'core.md'), `# Feature: core

**Keywords:** núcleo, base
**Resumo:** Núcleo.

## Specs desta feature

### Concluídas

### Planejadas (future/)

## Estado atual

Estado vivo que NÃO pode sair.

### Delta de estado

${deltas}
## Decisões arquiteturais ativas

- **DEC-20260610-1000-viva** (ativa) — decisão viva que NÃO pode sair.

## Alternativas consideradas e rejeitadas

## Gotchas

- SPEC-20251201-0900 — gotcha antigo: ${filler}

## Estado congelado (se houver)
`);
    expect(bytesOf(read(P(root, 'docs', 'features', 'core.md'))) > 8000, 'fixture deve começar acima de 8000B');
    const r = runCli(root, ['rollup', 'core']);
    expectRun(r, 0, 'rollup:', 'rollup');
    const after = norm(read(P(root, 'docs', 'features', 'core.md')));
    expect(bytesOf(after) <= 8000, `feature ainda acima do cap: ${bytesOf(after)}B`);
    expect(after.includes('Estado vivo que NÃO pode sair'), 'rollup tocou "Estado atual"');
    expect(after.includes('decisão viva que NÃO pode sair'), 'rollup tocou "Decisões arquiteturais ativas"');
    expect(after.includes('SPEC-20260112-1000'), 'rollup moveu bloco novo antes dos antigos');
    const hist = P(root, 'docs', 'features', 'core.history.md');
    expect(exists(hist), 'core.history.md não criado');
    const h = norm(read(hist));
    expect(h.includes('SPEC-20251201-0900'), 'bloco mais antigo (gotcha) não foi movido primeiro');
    expect(h.includes('SPEC-20260101-1000'), 'delta mais antigo não movido');
  });
  fixture('escalate-one-way', () => {
    const root = stBase(tmp, 'escalate');
    const id = stActiveSpec(root, { porte: 'P' });
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    const up = runCli(root, ['escalate', id, 'G']);
    expectRun(up, 0, 'P → G', 'escalate sobe');
    expect(norm(read(P(root, 'docs', 'active', id, 'main.md'))).includes('**Porte:** G'), 'Porte não atualizado no main.md');
    expect(norm(read(P(root, 'docs', 'active', id, 'journal.md'))).includes('[nota] Porte escalado P → G'), '[nota] de escalação ausente no LOG');
    const down = runCli(root, ['escalate', id, 'M']);
    expectRun(down, 1, 'ONE-WAY', 'escalate nega rebaixamento');
    const noCita = runCli(root, ['deescalate', id, 'M']);
    expectRun(noCita, 1, '--cita', 'deescalate sem --cita nega');
    const de = runCli(root, ['deescalate', id, 'M', '--cita', 'pode simplificar, M basta']);
    expectRun(de, 0, 'G → M', 'deescalate com citação');
    expect(norm(read(P(root, 'docs', 'active', id, 'main.md'))).includes('**Porte:** M'), 'Porte não rebaixado');
    const j = norm(read(P(root, 'docs', 'active', id, 'journal.md')));
    expect(/\[aceito-incompleto: "pode simplificar, M basta" \d{4}-\d{2}-\d{2} \d{2}:\d{2}\]/.test(j), `citação no padrão aceito-incompleto ausente — fim do journal: ${truncate(j.slice(-260), 260)}`);
  });
  fixture('close-pendencias', () => {
    const root = stBase(tmp, 'close-pend');
    const id = stActiveSpec(root, { criterios: ['- [ ] critério manual pendente'] });
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    const dry = runCli(root, ['close', id, '--dry']);
    expectRun(dry, 1, 'pendência', 'close --dry lista pendências');
    expect(dry.out.includes(`check ${id} 1`), `rota do check ausente — saída: ${truncate(dry.out, 400)}`);
    expect(dry.out.includes('[conclusão] ausente'), 'pendência de [conclusão] ausente');
    expect(dry.out.includes('R.7'), 'pendência R.7 ausente');
    expect(dry.out.includes('digest.md ausente'), 'pendência de digest ausente');
    expect(bytesOf(dry.out) <= 1300, `checklist --dry acima do orçamento: ${bytesOf(dry.out)}B`);
    const r = runCli(root, ['close', id]);
    expectRun(r, 1, 'pendência', 'close bloqueado imprime o MESMO checklist');
    expect(r.out.includes(`check ${id} 1`), 'checklist do close bloqueado sem rota');
    expect(isDir(P(root, 'docs', 'active', id)), 'close bloqueado NÃO pode mover a SPEC');
  });
  fixture('close-completo', () => {
    const root = stBase(tmp, 'close-ok');
    const id = stActiveSpec(root, { criterios: ['- [ ] roda ponta a ponta | verify: `node -e "process.exit(0)"`'] });
    writeFile(P(root, 'docs', 'active', id, 'journal.md'), stJournal(ST_ACT, { conclusao: true, snapshotDone: true }));
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(`SPEC-${ST_ACT}`));
    expect(stGitCommit(root), 'git commit indisponível na fixture');
    const dry = runCli(root, ['close', id, '--dry']);
    expectRun(dry, 0, 'pronto: SIM', 'close --dry pronto (só passos automáticos)');
    const r = runCli(root, ['close', id]);
    expectRun(r, 0, 'atestado', 'close completo');
    expect(r.out.includes('verify 1/1'), `atestado sem "verify 1/1" — saída: ${truncate(r.out, 400)}`);
    expect(r.out.includes('nada mais a rodar'), `atestado sem rodapé — saída: ${truncate(r.out, 400)}`);
    expect(r.out.includes('finalização') && r.out.includes('deletar a branch'), `atestado sem menu de finalização git — saída: ${truncate(r.out, 500)}`);
    expect(r.out.trim().split('\n').length <= 30, 'atestado acima de 30 linhas');
    expect(isDir(P(root, 'docs', 'archive', id)), 'SPEC não movida para docs/archive/');
    expect(exists(P(root, 'docs', 'archive', id, 'digest.md')), 'digest não gerado no close');
    expect(exists(P(root, 'docs', 'active', '.gitkeep')), 'docs/active/ sem .gitkeep após close — sumiria em checkout fresco (CI)');
    const main = norm(read(P(root, 'docs', 'archive', id, 'main.md')));
    expect(main.includes('**Status:** done') && /\*\*Commit final:\*\* `[0-9a-f]+`/.test(main), 'Status/Commit final não estampados');
    const again = runCli(root, ['close', id]);
    expectRun(again, 0, 'já está', 'close idempotente');
  });
  fixture('close-snapshot-stale', () => {
    // bug do bench porte-P: SPEC fechada só via scribe deixava o SNAPSHOT no placeholder e o digest herdava "nada feito ainda"
    const root = stBase(tmp, 'close-snap');
    const id = stActiveSpec(root, { criterios: ['- [x] feito (2026-01-12 12:00, commit `abc1234`)'] });
    writeFile(P(root, 'docs', 'active', id, 'journal.md'), stJournal(ST_ACT, { conclusao: true })); // SNAPSHOT = placeholder do template
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(`SPEC-${ST_ACT}`));
    const dry = runCli(root, ['close', id, '--dry']);
    expectRun(dry, 1, 'SNAPSHOT ainda com placeholder', 'close --dry bloqueia SNAPSHOT stale');
    // ao atualizar o SNAPSHOT, libera; e o digest gerado usa a [conclusão], não o placeholder
    const jp = P(root, 'docs', 'active', id, 'journal.md');
    writeFile(jp, read(jp).replace('início — nada feito ainda', 'entregue').replace('<primeiro passo concreto>', '—').replace('<fase>', 'impl'));
    expect(stGitCommit(root), 'git commit indisponível');
    const r = runCli(root, ['close', id]);
    expectRun(r, 0, 'atestado', 'close libera após SNAPSHOT atualizado');
    const dg = norm(read(P(root, 'docs', 'archive', id, 'digest.md')));
    expect(!/nada feito ainda/.test(dg), `digest herdou placeholder — saída: ${truncate(dg, 300)}`);
  });
  fixture('protected-branch', () => {
    // trabalho sempre em branch própria: new/activate proibidos em branch protegida (main/master/develop/homolog/hmg)
    const root = stBase(tmp, 'prot-branch'); // git init → branch default = main ou master (ambas protegidas)
    if (!stGitCommit(root)) return; // git indisponível: nada a exercitar (mesma postura das demais fixtures git)
    const r = runCli(root, ['new', 'demo', '--porte', 'P']);
    expectRun(r, 1, 'branch protegida', 'new em branch protegida deve morrer');
    expect(r.out.includes('feature/'), 'erro sem rota git checkout -b feature/');
    // em branch de feature: funciona e o claim registra a Base (a branch protegida ancestral)
    expect(stFeatureBranch(root), 'checkout feature/x falhou');
    const r2 = runCli(root, ['new', 'demo', '--porte', 'P']);
    expectRun(r2, 0, 'criada', 'new em feature/x deve funcionar');
    const id = (/(SPEC-\d{8}-\d{4}-demo)/.exec(r2.out) || [])[1];
    const claim = read(P(root, 'docs', 'claims', `${id}.md`));
    expect(/\*\*Base:\*\*\s*\S/.test(claim) && !/\*\*Base:\*\*\s*—/.test(claim), `claim sem Base detectada — ${truncate(claim, 200)}`);
  });
  // ---- Fase 2 (v4.1 comportamento) ----
  fixture('lint-porte-p-verify', () => {
    const root = stBase(tmp, 'lint-p-verify');
    stActiveSpec(root, { porte: 'P', criterios: ['- [ ] roda ponta a ponta | verify: `node -e "0"`'] });
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    const r = runCli(root, ['lint']);
    expectRun(r, 1, 'porte P não usa verify', 'lint P com verify: erra');
    expect(r.out.includes('specctl check'), 'erro P-verify sem rota specctl check');
  });
  fixture('makeMain-porte-p-scaffold', () => {
    const root = stBase(tmp, 'mkmain-p');
    const rn = runCli(root, ['new', 'exemplo-p', '--future', '--porte', 'P']);
    expectRun(rn, 0, '— fatos do sistema —', 'new --future P');
    const m = /criada docs\/future\/(SPEC-\S+)/.exec(rn.out);
    expect(m, `id não achado — saída: ${truncate(rn.out, 300)}`);
    const main = norm(read(P(root, 'docs', 'future', m[1], 'main.md')));
    expect(!/\|\s*verify:/.test(main.slice(main.indexOf('## Critério'))), 'scaffold P não deve ter slot verify:');
    expect(main.includes('<!-- P: feche com: node scripts/specctl.mjs check'), 'comentário auto-doc P ausente');
    const rg = runCli(root, ['new', 'exemplo-g', '--future', '--porte', 'G']);
    const mg = /criada docs\/future\/(SPEC-\S+)/.exec(rg.out);
    const mainG = norm(read(P(root, 'docs', 'future', mg[1], 'main.md')));
    expect(/\|\s*verify:/.test(mainG), 'scaffold M/G deve manter slot verify:');
  });
  fixture('guard-read-specctl', () => {
    const root = stBase(tmp, 'gr-specctl');
    const payload = JSON.stringify({ tool_name: 'Read', tool_input: { file_path: P(root, 'scripts', 'specctl.mjs') } });
    const d = runCli(root, ['guard-read'], payload);
    expectRun(d, 2, 'close <id> --dry', 'guard-read nega specctl (4.1.0)');
    expect(d.out.includes('--help'), 'redirect --help ausente');
    stManifest40(root);
    expectRun(runCli(root, ['guard-read'], payload), 0, null, 'guard-read permite specctl em 4.0.0');
  });
  fixture('guard-write-log-append', () => {
    const root = stBase(tmp, 'gw-log');
    stFeatureBranch(root);
    const id = stActiveSpec(root);
    const jp = P(root, 'docs', 'active', id, 'journal.md');
    const anchor = '## LOG (append-only — NUNCA editar entradas antigas)';
    const newEntry = `${anchor}\n\n## ${now()} — [nota] entrada manual do modelo\n\ncorpo qualquer\n`;
    const payload = JSON.stringify({ tool_name: 'Edit', tool_input: { file_path: jp, old_string: anchor, new_string: newEntry } });
    const d = runCli(root, ['guard-write'], payload);
    expectRun(d, 2, 'specctl log', 'guard-write nega LOG-append (4.1.0)');
    expect(d.out.includes('--stdin') && d.out.includes('--body-file'), 'deny sem copy-paste --stdin/--body-file');
    // SNAPSHOT/prosa continuam livres (Edit sem heading de LOG)
    const okSnap = JSON.stringify({ tool_name: 'Edit', tool_input: { file_path: jp, old_string: '**Onde tô:** início — nada feito ainda', new_string: '**Onde tô:** avancei bastante' } });
    expectRun(runCli(root, ['guard-write'], okSnap), 0, null, 'guard-write permite edição de SNAPSHOT');
    // com revision 4.0.0: permite o append (repo v4.0 não quebra)
    stManifest40(root);
    expectRun(runCli(root, ['guard-write'], payload), 0, null, 'guard-write permite LOG-append em 4.0.0');
  });
  fixture('guard-write-verify-spoof', () => {
    const root = stBase(tmp, 'gw-spoof');
    stFeatureBranch(root);
    const id = stActiveSpec(root);
    const mp = P(root, 'docs', 'active', id, 'main.md');
    const oldC = '- [ ] critério pendente | verify: `node -e "process.exit(0)"`';
    const spoof = '- [x] critério pendente (2026-01-12 10:00, commit `abc1234`, verify: exit 0) | verify: `node -e "process.exit(0)"`';
    const payload = JSON.stringify({ tool_name: 'Edit', tool_input: { file_path: mp, old_string: oldC, new_string: spoof } });
    const d = runCli(root, ['guard-write'], payload);
    expectRun(d, 2, 'só specctl verify grava evidência', 'guard-write nega verify-spoof (4.1.0)');
    stManifest40(root);
    expectRun(runCli(root, ['guard-write'], payload), 0, null, 'guard-write permite verify-spoof em 4.0.0');
  });
  fixture('brief-agent', () => {
    const root = stBase(tmp, 'brief-agent');
    const id = stActiveSpec(root);
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    runCli(root, ['index']);
    const r = runCli(root, ['brief', '--agent', id]);
    expectRun(r, 0, `bundle ${id}`, 'brief --agent bundle');
    expect(r.out.includes('== main.md ==') && r.out.includes('== SNAPSHOT'), 'bundle sem main.md/SNAPSHOT');
    expect(r.out.includes('Próximos passos'), 'bundle sem próximos passos');
    expect(r.out.includes('PROIBIDO varrer scripts/specctl.mjs'), 'HARD BAN 5 ausente no bundle');
  });
  fixture('audit-anti-fuga', () => {
    const root = stBase(tmp, 'audit-fuga');
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    stActiveSpecId(root, '20260701-1000', 'porte-p-grande', { porte: 'P', criterios: ['- [ ] c1', '- [ ] c2', '- [ ] c3', '- [ ] c4'] });
    stActiveSpecId(root, '20260701-1100', 'evidencia-spoof', { porte: 'M', criterios: ['- [x] roda (2026-01-12 10:00, commit `abc1234`, verify: exit 0) | verify: `node -e "0"`'] });
    const r = runCli(root, ['audit']);
    expectRun(r, 0, 'sinais de porte M', 'audit anti-fuga: P com >3 critérios');
    expect(r.out.includes('evidência sem rastro'), `audit "evidência sem rastro" ausente — saída: ${truncate(r.out, 500)}`);
  });
  fixture('audit-pr-porte-diff', () => {
    const root = stBase(tmp, 'audit-pr');
    const id = 'SPEC-20260701-1200-pr-diff';
    writeFile(P(root, 'docs', 'active', id, 'main.md'), stMain('20260701-1200', { status: 'active', porte: 'M', criterios: ['- [ ] c1'] }));
    writeFile(P(root, 'docs', 'active', id, 'journal.md'), stJournal('20260701-1200'));
    writeFile(P(root, 'docs', 'claims', `${id}.md`), makeClaim({ id, title: 'pr', owner: '@tester', branch: 'feature/x', features: 'core', ativada: '2026-01-10 10:05' }));
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    expect(stGitCommit(root), 'git commit base indisponível');
    const base = gitRun(['rev-parse', 'HEAD'], root).out;
    // muda Porte SEM entrada de journal + cresce a feature (crescer feature NUNCA bloqueia — sem ratchet)
    writeFile(P(root, 'docs', 'active', id, 'main.md'), stMain('20260701-1200', { status: 'active', porte: 'G', criterios: ['- [ ] c1'] }));
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore('') + '\n' + 'x'.repeat(8500) + '\n');
    expect(stGitCommit(root), 'git commit HEAD indisponível');
    const r = runCli(root, ['audit', '--pr', '--base', base]);
    expectRun(r, 1, 'Porte mudou', 'audit --pr: porte-diff sem journal erra');
    expect(!r.out.includes('ratchet'), `audit --pr NÃO deve mais ratchetar tamanho de feature — saída: ${truncate(r.out, 500)}`);
  });
  fixture('budgets-output', () => {
    const root = stBase(tmp, 'budgets');
    const rn = runCli(root, ['new', 'exemplo-budget', '--future', '--porte', 'P']);
    expectRun(rn, 0, '— fatos do sistema —', 'new imprime bloco JIT');
    const jitN = rn.out.slice(rn.out.indexOf('— fatos do sistema —'));
    expect(bytesOf(jitN) <= 900, `bloco JIT do new acima de 900B: ${bytesOf(jitN)}`);
    const m = /criada docs\/future\/(SPEC-\S+)/.exec(rn.out);
    expect(m, `id do new não achado — saída: ${truncate(rn.out, 300)}`);
    const id = m[1];
    const ra = runCli(root, ['activate', id, '--branch', 'feature/x']);
    expectRun(ra, 0, '— fatos do sistema —', 'activate imprime bloco JIT');
    const jitA = ra.out.slice(ra.out.indexOf('— fatos do sistema —'));
    expect(bytesOf(jitA) <= 900, `bloco JIT do activate acima de 900B: ${bytesOf(jitA)}`);
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    const dry = runCli(root, ['close', id, '--dry']);
    expect(bytesOf(dry.out) <= 1200, `close --dry acima de 1200B: ${bytesOf(dry.out)}`);
  });
  fixture('discard-gera-digest', () => {
    const root = stBase(tmp, 'discard-auto');
    stFeatureBranch(root);
    const id = stActiveSpec(root);
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    const r = runCli(root, ['discard', id, '--motivo', 'abordagem substituída por lib pronta']);
    expectRun(r, 0, 'digest gerado', 'discard gera digest automático (paridade com close)');
    const dg = P(root, 'docs', 'discard', id, 'digest.md');
    expect(exists(dg), 'digest.md não foi criado no discard');
    expect(digestMeasure(read(dg)) <= 2000, 'digest do discard acima de 2000B');
  });
  fixture('reopen-archive-para-active', () => {
    const root = stBase(tmp, 'reopen');
    stFeatureBranch(root);
    const id = stArchiveSpec(root);
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(`SPEC-${ST_ARCH}`));
    const r = runCli(root, ['reopen', id, '--motivo', 'critério 2 aceito sem autorização R.6.2']);
    expectRun(r, 0, 'reaberta', 'reopen move archive->active');
    expect(isDir(P(root, 'docs', 'active', id)), 'SPEC não voltou para docs/active/');
    const main2 = read(P(root, 'docs', 'active', id, 'main.md'));
    expect(/^\*\*Status:\*\* active/m.test(main2), 'Status não voltou a active');
    expect(/^\*\*Reaberta em:\*\*/m.test(main2), 'campo **Reaberta em:** ausente');
    expect(exists(P(root, 'docs', 'claims', `${id}.md`)), 'claim não recriado no reopen');
    const rf = runCli(root, ['reopen', 'SPEC-19990101-0000-inexistente', '--motivo', 'x']);
    expect(rf.code === 1, 'reopen de SPEC inexistente deveria falhar');
  });
  fixture('roadmap-entrada-morta', () => {
    const root = stBase(tmp, 'roadmap-morto');
    stArchiveSpec(root);
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(`SPEC-${ST_ARCH}`));
    writeFile(P(root, 'docs', 'ROADMAP.md'), `# ROADMAP\n\n1. SPEC-${ST_ARCH}-exemplo-arquivada\n2. SPEC-20990101-0000-typo-inexistente\n`);
    const r = runCli(root, ['lint']);
    expect(r.out.includes('NÃO EXISTE'), `lint sem warn de id inexistente no ROADMAP — saída: ${truncate(r.out, 400)}`);
    expect(r.out.includes('já em archive/'), `lint sem warn de entrada morta (arquivada) no ROADMAP — saída: ${truncate(r.out, 400)}`);
  });
  fixture('guard-write-segredo-pre', () => {
    const root = stBase(tmp, 'guard-secret');
    stActiveSpec(root);
    const payload = JSON.stringify({
      tool_name: 'Edit',
      tool_input: { file_path: P(root, 'docs', 'features', 'core.md'), old_string: 'x', new_string: 'chave: AKIAABCDEFGHIJKLMNOP' },
    });
    expectRun(runCli(root, ['guard-write'], payload), 2, 'R.15', 'guard-write nega segredo PRÉ-write');
  });
  fixture('guard-read-grep-archive', () => {
    const root = stBase(tmp, 'guard-grep');
    stActiveSpec(root);
    stArchiveSpec(root);
    const payload = JSON.stringify({ tool_name: 'Grep', tool_input: { pattern: 'x', path: P(root, 'docs', 'archive') } });
    expectRun(runCli(root, ['guard-read'], payload), 2, 'R.8', 'guard-read nega Grep em archive/');
    const free = JSON.stringify({ tool_name: 'Grep', tool_input: { pattern: 'x', path: P(root, 'src') } });
    expectRun(runCli(root, ['guard-read'], free), 0, null, 'Grep fora de docs/ segue livre');
  });
  fixture('team-multi-claim', () => {
    const root = stBase(tmp, 'team-multi');
    // manifesto team: multi
    const man = JSON.parse(read(P(root, 'docs', '.spec-system.json')));
    man.team = 'multi';
    writeFile(P(root, 'docs', '.spec-system.json'), JSON.stringify(man, null, 2) + '\n');
    stFeatureBranch(root);
    // new + activate → coreografia de publicação impressa
    const rn = runCli(root, ['new', 'claim-multi', '--future', '--porte', 'P', '--features', 'core']);
    const id = (/(SPEC-\d{8}-\d{4}-claim-multi)/.exec(rn.out) || [])[1];
    expect(id, `id não extraído — saída: ${truncate(rn.out, 300)}`);
    const ra = runCli(root, ['activate', id, '--branch', 'feature/x']);
    expectRun(ra, 0, 'team: multi', 'activate multi imprime coreografia');
    expect(ra.out.includes(`claim/${id}`) && ra.out.includes('PR trivial'), `coreografia ausente — saída: ${truncate(ra.out, 400)}`);
    // capsule carrega team=multi
    const rc = runCli(root, ['capsule']);
    expect(rc.out.includes('team=multi'), `capsule sem team=multi — saída: ${truncate(rc.out, 200)}`);
    // audit avisa claim não publicado na base (claim só existe na feature/x)
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(''));
    expect(stGitCommit(root), 'commit indisponível');
    const rau = runCli(root, ['audit']);
    expect(rau.out.includes('NÃO publicado'), `audit sem aviso de claim não-publicado — saída: ${truncate(rau.out, 400)}`);
    // em solo, mesmo cenário NÃO avisa
    man.team = 'solo';
    writeFile(P(root, 'docs', '.spec-system.json'), JSON.stringify(man, null, 2) + '\n');
    const rau2 = runCli(root, ['audit']);
    expect(!rau2.out.includes('NÃO publicado'), 'audit solo não deveria avisar publicação');
  });
  fixture('deferred-index', () => {
    const root = stBase(tmp, 'deferred');
    stArchiveSpec(root, {
      criterios: [
        '- [x] Feito (2026-01-12 11:50, commit `abc1234`, verify: exit 0)',
        '- [ ] Item deferido [aceito-incompleto: "pode deixar pra v2" 2026-01-12 11:55]',
      ],
    });
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(`SPEC-${ST_ARCH}`));
    expectRun(runCli(root, ['index']), 0, null, 'index');
    const def = read(P(root, 'docs', 'DEFERRED.md'));
    expect(def.includes('pode deixar pra v2'), 'DEFERRED.md sem a citação do item deferido');
    expect(def.includes(`SPEC-${ST_ARCH}-exemplo-arquivada`), 'DEFERRED.md sem o SPEC-id');
    expectRun(runCli(root, ['lint']), 0, null, 'lint com DEFERRED gerado');
  });

  fixture('fence-nao-esconde-criterio', () => {
    const root = stBase(tmp, 'fence-crit');
    const id = `SPEC-${ST_ARCH}-exemplo-arquivada`;
    const dir = P(root, 'docs', 'archive', id);
    // fence com "# comentário" ANTES de um critério aberto: parser antigo achava que a seção acabou ali
    writeFile(P(dir, 'main.md'), stMain(ST_ARCH, {
      status: 'done', concluida: '2026-01-12 12:00', commitFinal: '`abc1234`',
      criterios: [
        '- [x] Feito (2026-01-12 11:50, commit `abc1234`, verify: exit 0)',
        'Exemplo de uso:',
        '```bash',
        '# roda os testes',
        'npm test',
        '- [x] isto é EXEMPLO dentro do fence, não critério',
        '```',
        '- [ ] critério REAL aberto depois do fence',
      ],
    }));
    writeFile(P(dir, 'journal.md'), stJournal(ST_ARCH, { conclusao: true }));
    writeFile(P(dir, 'digest.md'), '# Digest\n\nok.\n');
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(`SPEC-${ST_ARCH}`));
    const r = runCli(root, ['lint']);
    expectRun(r, 1, 'aceito-incompleto', 'lint DEVE ver o critério aberto escondido atrás do fence');
    expect(!r.out.includes('EXEMPLO dentro do fence') || !/aceito-incompleto[^\n]*EXEMPLO/.test(r.out), 'checkbox de exemplo dentro do fence não deveria ser tratado como critério');
  });
  fixture('status-mesmo-minuto', () => {
    const root = stBase(tmp, 'same-minute');
    const a = 'SPEC-20260101-1000-alpha';
    const b = 'SPEC-20260101-1000-beta';
    writeFile(P(root, 'docs', 'archive', a, 'main.md'), stMain('20260101-1000', { status: 'done', concluida: '2026-01-02 12:00', commitFinal: '`abc1234`', criterios: ['- [x] ok (2026-01-02 11:50, commit `abc1234`, verify: exit 0)'] }));
    writeFile(P(root, 'docs', 'archive', a, 'journal.md'), stJournal('20260101-1000', { conclusao: true }));
    writeFile(P(root, 'docs', 'archive', a, 'digest.md'), '# Digest\n\nok.\n');
    writeFile(P(root, 'docs', 'future', b, 'main.md'), stMain('20260101-1000', { status: 'draft', ativada: '—' }));
    writeFile(P(root, 'docs', 'programs', 'gamma.md'), `# Programa: gamma\n\n**Owner:** @tester\n\n- ${a} | depende de: —\n- ${b} | depende de: ${a}\n`);
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(`SPEC-20260101-1000`));
    const r = runCli(root, ['next']);
    // com o bug, `a` (done) resolvia o status de `b` (draft) — e b nunca ficava pronto
    expect(r.out.includes(b) && /▶|pronto/i.test(r.out), `nó b deveria estar PRONTO (dep done) — saída: ${truncate(r.out, 300)}`);
  });
  fixture('fence-nao-prova-r7', () => {
    const root = stBase(tmp, 'fence-r7');
    stFeatureBranch(root);
    const id = stActiveSpec(root, { porte: 'P', criterios: ['- [x] Feito (2026-01-10 11:00, commit `abc1234`) — check'] });
    // SPEC-id só DENTRO de fence na seção Concluídas — não pode contar como R.7
    writeFile(P(root, 'docs', 'features', 'core.md'), `# Feature: core

**Keywords:** núcleo
**Arquivos principais:**
  - src/core.ts
**Resumo:** exemplo.

## Specs desta feature

### Concluídas

\`\`\`
- ${id} | formato de exemplo, não é entrada real
\`\`\`

## Estado atual

x

## Decisões arquiteturais ativas

## Gotchas
`);
    const r = runCli(root, ['close', id, '--dry']);
    expect(r.code === 1 && r.out.includes('R.7'), `close --dry DEVE bloquear R.7 com id só em fence — saída: ${truncate(r.out, 300)}`);
  });
  fixture('close-roda-suite', () => {
    const root = stBase(tmp, 'close-suite');
    stFeatureBranch(root);
    const id = stActiveSpec(root, { porte: 'P', criterios: ['- [x] Feito (2026-01-10 11:00, commit `abc1234`) — check'] });
    writeFile(P(root, 'docs', 'features', 'core.md'), stFeatureCore(idPrefix(id)));
    writeFile(P(root, 'docs', 'active', id, 'journal.md'), stJournal(ST_ACT, { conclusao: true, snapshotDone: true }));
    expect(stGitCommit(root), 'git commit indisponível na fixture');
    // manifesto com label test que FALHA → close aborta sem mover
    const man = JSON.parse(read(P(root, 'docs', '.spec-system.json')));
    man.commands.test = `${JSON.stringify(process.execPath).slice(1, -1)} -e "process.exit(1)"`;
    writeFile(P(root, 'docs', '.spec-system.json'), JSON.stringify(man, null, 2) + '\n');
    const rf = runCli(root, ['close', id]);
    expect(rf.code === 1 && rf.out.includes('suíte do projeto falhou'), `close deveria abortar com suíte falhando — saída: ${truncate(rf.out, 300)}`);
    expect(isDir(P(root, 'docs', 'active', id)), 'SPEC não pode ter sido movida com suíte falhando');
    // suíte passa → close completa e atestado mostra suite PASS
    man.commands.test = `${JSON.stringify(process.execPath).slice(1, -1)} -e "process.exit(0)"`;
    writeFile(P(root, 'docs', '.spec-system.json'), JSON.stringify(man, null, 2) + '\n');
    const ok = runCli(root, ['close', id]);
    expectRun(ok, 0, 'suite PASS', 'close com suíte passando');
    expect(isDir(P(root, 'docs', 'archive', id)), 'SPEC deveria estar em archive/');
  });

  out(`== specctl self-test (v${VERSION}) ==`);
  let pass = 0;
  for (const [name, ok, why] of results) {
    if (ok) { pass++; out(`PASS  ${name}`); }
    else out(`FAIL  ${name} — ${why}`);
  }
  out(`\nResultado: ${pass}/${results.length} PASS`);
  const allOk = pass === results.length;
  if (allOk) { try { fs.rmSync(tmp, { recursive: true, force: true }); } catch { out(`(fixtures mantidas em ${tmp} — remoção falhou)`); } }
  else out(`fixtures preservadas para inspeção em: ${tmp}`);
  process.exit(allOk ? 0 : 1);
}

// ---------------------------------------------------------------- dispatch

const VALUE_FLAGS = ['base', 'motivo', 'porte', 'owner', 'features', 'program', 'workspace', 'branch', 'evidence', 'body-file', 'file', 'cita', 'agent'];
function parseArgs(argv) {
  const flags = {}; const pos = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const eq = a.indexOf('=');
      if (eq > -1) flags[a.slice(2, eq)] = a.slice(eq + 1);
      else {
        const name = a.slice(2);
        if (VALUE_FLAGS.includes(name)) {
          flags[name] = argv[++i];
          if (flags[name] === undefined) die(`--${name} exige valor`);
        } else flags[name] = true;
      }
    } else pos.push(a);
  }
  return { flags, pos };
}
function usage() {
  process.stderr.write(`specctl v${VERSION} (${SCHEMA}) — CLI única do sistema SPEC (SDD v4)
uso: node scripts/specctl.mjs <comando> [args]

ciclo de vida:  init · new · activate · pause · resume · reopen <id> --motivo "..." · close <id> [--dry] · archive · discard
                new: em main/master só --future é permitido (R.2) — SPEC ativa exige branch de feature
                close: fechamento transacional (verify+digest+archive) — comece por close <id> --dry
                reopen: archive→active (correção R.6.2 — fechamento indevido); discard não reabre
scribe:         log <id> <tipo> "título" [--stdin|--body-file <f>] · check <id> <n> [--evidence "..."]
fechamento:     digest <id> [--stdin|--file <f>] [--fix] · rollup <area> · escalate <id> <M|G> · deescalate <id> <P|M> --cita "..."
validação:      lint [--strict] [--target-main] · audit [--pr --base <sha>] [--deps] [--main-gate] · verify <id> [--all] · self-test
contexto:       brief [--compact] [--agent <id>] · capsule · stamp · index · next [--program <slug>] · entrypoints · adopt-workspace <id>
hooks:          guard-read · guard-write · stamp-check · session-close
`);
  process.exit(1);
}

const [, , cmd, ...rest] = process.argv;
const { flags, pos } = parseArgs(rest);
try {
  switch (cmd) {
    case 'init': cmdInit(flags); break;
    case 'new': cmdNew(pos, flags); break;
    case 'activate': cmdActivate(pos, flags); break;
    case 'pause': cmdPause(pos, flags); break;
    case 'resume': cmdResume(pos); break;
    case 'reopen': cmdReopen(pos, flags); break;
    case 'archive': cmdArchive(pos); break;
    case 'discard': cmdDiscard(pos, flags); break;
    case 'lint': cmdLint(flags); break;
    case 'audit': cmdAudit(flags); break;
    case 'index': cmdIndex(); break;
    case 'next': cmdNext(null, flags); break;
    case 'brief': cmdBrief(flags); break;
    case 'capsule': cmdCapsule(); break;
    case 'stamp': cmdStamp(); break;
    case 'verify': cmdVerify(pos, flags); break;
    case 'log': cmdLog(pos, flags); break;
    case 'check': cmdCheck(pos, flags); break;
    case 'digest': cmdDigest(pos, flags); break;
    case 'rollup': cmdRollup(pos); break;
    case 'escalate': cmdEscalate(pos); break;
    case 'deescalate': cmdDeescalate(pos, flags); break;
    case 'close': cmdClose(pos, flags); break;
    case 'guard-read': cmdGuardRead(); break;
    case 'guard-write': cmdGuardWrite(); break;
    case 'stamp-check': cmdStampCheck(); break;
    case 'session-close': cmdSessionClose(); break;
    case 'adopt-workspace': cmdAdoptWorkspace(pos); break;
    case 'entrypoints': cmdEntrypoints(); break;
    case 'self-test': cmdSelfTest(); break;
    case '--version': case 'version': out(`specctl ${VERSION} (${SCHEMA})`); break;
    default: usage();
  }
} catch (e) {
  die(`falha inesperada em '${cmd}': ${e.message}${process.env.SPECCTL_DEBUG ? '\n' + e.stack : ''}`);
}
