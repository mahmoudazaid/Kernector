import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "default" | "secondary" | "ghost";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  children: ReactNode;
};

const variantClass: Record<ButtonVariant, string> = {
  default: "kern-btn",
  secondary: "kern-btn kern-btn-secondary",
  ghost: "kern-btn kern-btn-ghost",
};

export function Button({
  variant = "default",
  className,
  children,
  type = "button",
  ...props
}: ButtonProps) {
  const classes = [variantClass[variant], className].filter(Boolean).join(" ");
  return (
    <button type={type} className={classes} {...props}>
      {children}
    </button>
  );
}
