import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

const stateRoot = join(process.cwd(), 'state');

// Write a text file under state/, creating parent folders and ensuring a single trailing
// newline for stable diffs.
export function writeStateText(relativePath: string, content: string): string {
  const target = join(stateRoot, relativePath);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, content.endsWith('\n') ? content : `${content}\n`, 'utf8');
  return target;
}

// Write a JSON file under state/ from a model, deterministic two-space indent.
export function writeStateJson(relativePath: string, model: unknown): string {
  return writeStateText(relativePath, `${JSON.stringify(model, null, 2)}\n`);
}

// Remove a folder under state/ and everything in it, so a regenerated tree never keeps
// files for objects that no longer exist.
export function cleanStateDir(relativePath: string): void {
  rmSync(join(stateRoot, relativePath), { recursive: true, force: true });
}

// Render a Markdown table. Cell content is escaped so pipes and newlines never break the
// table structure.
export function markdownTable(headers: string[], rows: string[][]): string {
  const headerLine = `| ${headers.join(' | ')} |`;
  const separatorLine = `| ${headers.map(() => '---').join(' | ')} |`;
  if (rows.length === 0) {
    return `${headerLine}\n${separatorLine}`;
  }
  const bodyLines = rows.map((row) => `| ${row.map(escapeCell).join(' | ')} |`);
  return [headerLine, separatorLine, ...bodyLines].join('\n');
}

export function escapeCell(value: string): string {
  return value.replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');
}

// Inline code, used for identifiers and short type or default text in prose and cells.
export function code(value: string): string {
  return `\`${value}\``;
}

// A heading line at the given level with the given text.
export function heading(level: number, text: string): string {
  return `${'#'.repeat(level)} ${text}`;
}
