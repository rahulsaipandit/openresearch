// Frontend Component Requirement #2: renders analysis text with inline
// citation markers ([1], [2], ...) linked to entries in ResearchBrief.sources
// — every generated claim should be traceable to a source in the UI, not
// just in the raw JSON (see AI Requirements / auditability in requirements.md).

interface CitedTextProps {
  text: string;
  sources: string[];
}

export function CitedText({ text, sources }: CitedTextProps) {
  const parts = text.split(/(\[\d+\])/g);

  return (
    <div className="cited-text">
      <p>
        {parts.map((part, i) => {
          const match = part.match(/^\[(\d+)\]$/);
          if (!match) return <span key={i}>{part}</span>;
          const idx = Number(match[1]) - 1;
          const source = sources[idx];
          return (
            <a
              key={i}
              className="citation-chip"
              href={source ?? "#"}
              target="_blank"
              rel="noreferrer"
              title={source ?? "Source unavailable"}
            >
              {match[0]}
            </a>
          );
        })}
      </p>
      {sources.length > 0 && (
        <ol className="citation-list">
          {sources.map((s, i) => (
            <li key={i}>
              <a href={s} target="_blank" rel="noreferrer">
                {s}
              </a>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
