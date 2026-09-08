// Generic readable renderer for nested data snapshots (real estate's
// migration/labor/housing/etc. schemas are numerous and deep) — humanizes
// snake_case keys and recurses one level into nested objects/arrays, so
// results read as a labeled list instead of a raw JSON dump.

function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(value: unknown): React.ReactNode {
  if (value === null || value === undefined || value === "") {
    return <span className="muted">N/A</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="muted">None</span>;
    if (typeof value[0] === "object" && value[0] !== null) {
      return (
        <ul className="nested-list">
          {value.map((v, i) => (
            <li key={i}>
              <KeyValueList data={v as Record<string, unknown>} />
            </li>
          ))}
        </ul>
      );
    }
    return value.join(", ");
  }
  if (typeof value === "object") {
    return <KeyValueList data={value as Record<string, unknown>} />;
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? value : value.toFixed(2);
  }
  return String(value);
}

interface KeyValueListProps {
  data: Record<string, unknown>;
}

export function KeyValueList({ data }: KeyValueListProps) {
  const entries = Object.entries(data).filter(([, v]) => v !== null && v !== undefined);
  if (entries.length === 0) return <span className="muted">No data</span>;

  return (
    <table className="kv-table">
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k}>
            <th>{humanize(k)}</th>
            <td>{formatValue(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
