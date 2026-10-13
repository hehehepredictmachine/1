import { usePersisted } from "../router";

/** Collapsible secondary section with a persisted open state. */
export default function Section({ id, title, children, defaultOpen = false, testid }: { id: string; title: React.ReactNode; children: React.ReactNode; defaultOpen?: boolean; testid?: string }) {
  const [open, setOpen] = usePersisted<boolean>(`sec.${id}`, defaultOpen, (x) => typeof x === "boolean");
  return (
    <details className="sec" open={open} data-testid={testid} onToggle={(e) => { const o = (e.currentTarget as HTMLDetailsElement).open; if (o !== open) setOpen(o); }}>
      <summary><h3>{title}</h3></summary>
      {open && <div className="sec-body">{children}</div>}
    </details>
  );
}

