type KernectorLoaderMarkProps = {
  className?: string;
};

export function KernectorLoaderMark({ className }: KernectorLoaderMarkProps) {
  return (
    // Official animated SVG must load as an image so the blink runs in Safari.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      className={className}
      src="/brand/kernector-loader.svg"
      alt=""
      width={72}
      height={68}
    />
  );
}
