import { KernectorLoaderMark } from "@/components/shell/KernectorLoaderMark";

type LoaderSize = "sm" | "md" | "lg";

type LoaderProps = {
  label: string;
  size?: LoaderSize;
  className?: string;
};

export function Loader({ label, size = "md", className }: LoaderProps) {
  const classes = ["kern-loader", `kern-loader--${size}`, className]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} role="status">
      <KernectorLoaderMark className="kern-loader-mark" />
      <span className="visually-hidden">{label}</span>
    </div>
  );
}
