import type { ReactNode } from 'react'

function inline(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean)
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${keyPrefix}-${index}`}>{part.slice(2, -2)}</strong>
    }
    return <span key={`${keyPrefix}-${index}`}>{part}</span>
  })
}

function tableCells(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}

function isDivider(cells: string[]): boolean {
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

export function ReportText({ text }: { text: string }) {
  const lines = text.split(/\r?\n/)
  const blocks: ReactNode[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    const trimmed = line.trim()
    if (!trimmed) {
      index += 1
      continue
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed)
    if (heading) {
      const level = Math.min(heading[1].length + 1, 6)
      blocks.push(
        <h2 key={`heading-${index}`} data-level={level} className={`report-heading report-heading--${level}`}>
          {inline(heading[2], `heading-${index}`)}
        </h2>,
      )
      index += 1
      continue
    }

    if (trimmed.startsWith('|')) {
      const tableLines: string[] = []
      while (index < lines.length && lines[index].trim().startsWith('|')) {
        tableLines.push(lines[index].trim())
        index += 1
      }
      const header = tableCells(tableLines[0])
      const rows = tableLines.slice(1).map(tableCells).filter((cells) => !isDivider(cells))
      blocks.push(
        <div key={`table-${index}`} className="report-table-wrap">
          <table className="report-table">
            <thead>
              <tr>{header.map((cell, cellIndex) => <th key={`th-${cellIndex}`}>{inline(cell, `th-${index}-${cellIndex}`)}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((cells, rowIndex) => (
                <tr key={`tr-${rowIndex}`}>
                  {cells.map((cell, cellIndex) => <td key={`td-${cellIndex}`}>{inline(cell, `td-${index}-${rowIndex}-${cellIndex}`)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }

    if (/^[-*]\s+/.test(trimmed)) {
      const items: string[] = []
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ''))
        index += 1
      }
      blocks.push(
        <ul key={`list-${index}`} className="report-list">
          {items.map((item, itemIndex) => <li key={`li-${itemIndex}`}>{inline(item, `li-${index}-${itemIndex}`)}</li>)}
        </ul>,
      )
      continue
    }

    const paragraph: string[] = [trimmed]
    index += 1
    while (index < lines.length) {
      const next = lines[index].trim()
      if (!next || /^(#{1,4})\s+/.test(next) || next.startsWith('|') || /^[-*]\s+/.test(next)) break
      paragraph.push(next)
      index += 1
    }
    blocks.push(<p key={`paragraph-${index}`}>{inline(paragraph.join(' '), `paragraph-${index}`)}</p>)
  }

  return <div className="report-text">{blocks}</div>
}
