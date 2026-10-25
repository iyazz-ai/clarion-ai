export const CATEGORIES = [
  "Models",
  "Agents",
  "Research",
  "Products",
  "Business",
  "Developer Tools",
  "Safety",
  "Other",
];

export default function CategoryTabs({ value, onChange }) {
  return (
    <div className="chips" role="tablist" aria-label="Categories">
      {["", ...CATEGORIES].map((category) => (
        <button
          key={category || "all"}
          role="tab"
          aria-selected={value === category}
          className={`chip ${value === category ? "active" : ""}`}
          onClick={() => onChange(category)}
        >
          {category || "All"}
        </button>
      ))}
    </div>
  );
}