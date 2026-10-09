import { Fragment, type ReactNode } from 'react';

/** Render only safe Markdown emphasis, code, headings and lists, never model HTML. */
function inline(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const token = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*)/g;
  let pos = 0;
  for (const match of text.matchAll(token)) {
    const index = match.index ?? pos;
    if (index > pos) parts.push(text.slice(pos, index));
    const word = match[0];
    const key = `${index}-${word.length}`;
    if (word.startsWith('`')) parts.push(<code key={key}>{word.slice(1, -1)}</code>);
    else if (word.startsWith('**') || word.startsWith('__')) parts.push(<strong key={key}>{word.slice(2, -2)}</strong>);
    else parts.push(<em key={key}>{word.slice(1, -1)}</em>);
    pos = index + word.length;
  }
  if (pos < text.length) parts.push(text.slice(pos));
  return parts;
}

export function SafeAIText({ content }: { content: string }) {
  const lines = content.split(/\r?\n/);
  const output: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    const list = /^\s*(?:[-*]\s+|\d+\.\s+)/.exec(line);
    if (list) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const items: ReactNode[] = [];
      while (index < lines.length && (ordered ? /^\s*\d+\.\s+/.test(lines[index]) : /^\s*[-*]\s+/.test(lines[index]))) {
        items.push(<li key={index}>{inline(lines[index].replace(/^\s*(?:[-*]|\d+\.)\s+/, ''))}</li>);
        index += 1;
      }
      output.push(ordered ? <ol key={`list-${index}`}>{items}</ol> : <ul key={`list-${index}`}>{items}</ul>);
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      output.push(<p className="ai-markdown__heading" key={index}><strong>{inline(heading[2])}</strong></p>);
      index += 1;
      continue;
    }
    const rows: ReactNode[] = [];
    while (index < lines.length && lines[index].trim() && !/^\s*(?:[-*]\s+|\d+\.\s+|#{1,3}\s+)/.test(lines[index])) {
      if (rows.length) rows.push(<Fragment key={`break-${index}`}><br /></Fragment>);
      rows.push(<Fragment key={index}>{inline(lines[index])}</Fragment>);
      index += 1;
    }
    output.push(<p key={`p-${index}`}>{rows}</p>);
  }
  return <div className="ai-markdown">{output}</div>;
}
