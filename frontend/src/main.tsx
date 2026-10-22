import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import Glyph, { GLYPH_NAMES } from "./Glyph";
import "./index.css";

// #glyphs shows the whole pictogram library (a reference for coaches and reviewers).
const Sheet = () => (
  <div className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-3 p-6">
    {GLYPH_NAMES.map((g) => <figure key={g} className="flex flex-col items-center gap-1 rounded-md border border-rule bg-card p-2 text-sm">
      <Glyph name={g} label={g} size={88} /><figcaption>{g}</figcaption></figure>)}
  </div>
);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>{location.hash === "#glyphs" ? <Sheet /> : <App />}</React.StrictMode>,
);
