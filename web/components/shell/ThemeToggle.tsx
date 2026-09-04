"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const isDark = mounted && resolvedTheme === "dark";

  return (
    <button
      className="kern-theme"
      type="button"
      aria-label="Toggle color theme"
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      <svg
        className="kern-theme-icon"
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
      >
        {isDark ? (
          <circle cx="8" cy="8" r="5" stroke="currentColor" strokeWidth="1.5" />
        ) : (
          <path
            d="M9.5 2.2A5.8 5.8 0 0 0 2.2 9.5 5.8 5.8 0 1 0 9.5 2.2Z"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        )}
      </svg>
      <span>{mounted ? (isDark ? "Light" : "Dark") : "Theme"}</span>
    </button>
  );
}
