import { Link, NavLink } from "react-router-dom";

export default function Header() {
  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="Clarion AI home">
        <span className="brand-mark">C</span>
        <span className="brand-name">Clarion AI</span>
      </Link>

      <nav className="nav" aria-label="Main">
        <NavLink to="/" end>Feed</NavLink>
        <NavLink to="/trending">Trending</NavLink>
        <NavLink to="/search">Search</NavLink>
      </nav>
    </header>
  );
}