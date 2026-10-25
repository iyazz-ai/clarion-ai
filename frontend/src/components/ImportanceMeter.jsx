export default function ImportanceMeter({ score = 0, showLabel = true }) {
  const value = Math.max(0, Math.min(100, Math.round(score)));

  return (
    <div
      className="importance"
      title={`Importance score: ${value} / 100`}
      aria-label={`Importance ${value} out of 100`}
    >
      <div className="importance-track">
        <div className="importance-fill" style={{ width: `${value}%` }} />
      </div>
      <span className="importance-value">
        {value}
        {showLabel && <small> / 100</small>}
      </span>
    </div>
  );
}