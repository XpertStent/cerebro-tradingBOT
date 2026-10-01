import React, { useState } from "react";
import { ChevronDown } from "lucide-react";
import "./CollapsibleSection.css";

export default function CollapsibleSection({
  title,
  subtitle = null,
  actions = null,
  footer = null,
  defaultOpen = true,
  className = "",
  children,
  bodyClassName = ""
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className={`collapsibleSection ${className}`.trim()}>
      <div className="collapsibleHeader">
        <button
          type="button"
          className="collapsibleToggle"
          onClick={() => setOpen(value => !value)}
          aria-expanded={open}
        >
          <ChevronDown
            size={18}
            className={open ? "collapsibleChevron open" : "collapsibleChevron"}
          />
          <div>
            <h2>{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
        </button>
        {actions ? <div className="collapsibleActions">{actions}</div> : null}
      </div>
      {open ? (
        <>
          <div className={`collapsibleBody ${bodyClassName}`.trim()}>
            {children}
          </div>
          {footer ? <div className="collapsibleFooter">{footer}</div> : null}
        </>
      ) : null}
    </section>
  );
}
