import {
  forwardRef,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";

type ButtonVariant = "default" | "secondary" | "ghost" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  children: ReactNode;
};

const variantClass: Record<ButtonVariant, string> = {
  default: "kern-btn",
  secondary: "kern-btn kern-btn-secondary",
  ghost: "kern-btn kern-btn-ghost",
  danger: "kern-btn kern-btn-danger",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", className, children, type = "button", ...props },
  ref,
) {
  const classes = [variantClass[variant], className].filter(Boolean).join(" ");
  return (
    <button ref={ref} type={type} className={classes} {...props}>
      {children}
    </button>
  );
});
