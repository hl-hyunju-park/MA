import { useRef, type KeyboardEvent } from "react";

// Auto-resizing textarea + send button. Enter submits, Shift+Enter newlines.
export default function Composer({
  value,
  onChange,
  onSubmit,
  busy,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const resize = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  };

  return (
    <div className="composer">
      <textarea
        ref={ref}
        rows={1}
        value={value}
        placeholder="예: 기업가치는 얼마인가요?"
        onChange={(e) => {
          onChange(e.target.value);
          resize();
        }}
        onKeyDown={onKey}
      />
      <button onClick={onSubmit} disabled={busy || value.trim() === ""}>
        전송
      </button>
    </div>
  );
}
