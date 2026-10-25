export function LoadingList({ rows = 4 }) {
  return (
    <div className="story-list" aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }).map((_, i) => (
        <div className="story skeleton" key={i}>
          <div className="story-body">
            <div className="sk sk-line sk-short" />
            <div className="sk sk-title" />
            <div className="sk sk-line" />
            <div className="sk sk-line sk-medium" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry }) {
  return (
    <div className="state" role="alert">
      <div className="state-icon">!</div>
      <h3>Something went wrong</h3>
      <p>{error?.message || "Unable to load stories."}</p>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, text, actionLabel, onAction }) {
  return (
    <div className="state">
      <div className="state-icon">⌕</div>
      <h3>{title}</h3>
      <p>{text}</p>
      {onAction && (
        <button className="btn" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}