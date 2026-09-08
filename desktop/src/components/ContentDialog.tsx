import { useEffect, type ReactNode } from "react";

// Frontend Component Requirement #4: a simple modal for showing longer
// content (filing excerpts, full earnings-call summary, source snippets)
// without navigating away from the main view. Kept deliberately minimal —
// see requirements.md: "don't over-invest in this one."

interface ContentDialogProps {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function ContentDialog({ title, open, onClose, children }: ContentDialogProps) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    if (open) document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog-panel" onClick={(e) => e.stopPropagation()}>
        <div className="dialog-header">
          <h3>{title}</h3>
          <button type="button" className="dialog-close" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>
        <div className="dialog-body">{children}</div>
      </div>
    </div>
  );
}
