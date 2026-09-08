type KernectorThinkingMarkProps = {
  className?: string;
};

export function KernectorThinkingMark({
  className,
}: KernectorThinkingMarkProps) {
  return (
    <svg
      className={className}
      viewBox="-2.15 -80.15 175.3 235.4"
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <clipPath id="kern-thinking-b">
          <path d="M37.18 134.9L57.78 114.3A12.12 12.12 0 0 0 40.65 97.17L20.05 117.77A12.12 12.12 0 0 0 37.18 134.9Z" />
        </clipPath>
        <clipPath id="kern-thinking-a">
          <path d="M114.3 57.78L134.9 37.18A12.12 12.12 0 0 0 117.77 20.05L97.17 40.65A12.12 12.12 0 0 0 114.3 57.78Z" />
        </clipPath>
      </defs>
      <g className="kern-thinking-body">
        <path d="M15.2 89.39L15.2 6.4A3.2 3.2 0 0 1 18.4 3.2L49.6 3.2A3.2 3.2 0 0 1 52.8 6.4L52.8 58.36A1.5 1.5 0 0 0 55.36 59.42L69.72 45.05A1.5 1.5 0 0 1 72.27 45.9L75.19 66.17A3.2 3.2 0 0 1 74.29 68.89L70.32 72.86A3.2 3.2 0 0 1 68.06 73.8L38.44 73.8A3.2 3.2 0 0 0 36.37 74.56L17.68 90.53A1.5 1.5 0 0 1 15.2 89.39Z" />
        <path d="M163.45 154.9L118.14 154.9A3.2 3.2 0 0 1 115.74 153.81L83.36 116.97A3.2 3.2 0 0 1 82.58 115.21L79.79 89.58A3.2 3.2 0 0 1 80.71 86.97L85.64 82.04A3.2 3.2 0 0 1 87.9 81.1L110.49 81.1A1.5 1.5 0 0 1 111.55 83.66L109.15 86.06A3.2 3.2 0 0 0 109.05 90.47L163.98 150.96A3.2 3.2 0 0 1 164.81 153.11L164.81 153.54A1.36 1.36 0 0 1 163.45 154.9Z" />
        <path
          fillRule="evenodd"
          d="M48.7 146.71L69.59 125.82A28.61 28.61 0 0 0 29.13 85.37L8.25 106.25A28.61 28.61 0 0 0 48.7 146.71ZM36.86 134.58L57.46 113.98A11.67 11.67 0 0 0 40.97 97.49L20.37 118.09A11.67 11.67 0 0 0 36.86 134.58Z"
        />
      </g>
      <path
        className="kern-thinking-accent"
        fillRule="evenodd"
        d="M125.82 69.59L146.71 48.7A28.61 28.61 0 0 0 106.25 8.25L85.37 29.13A28.61 28.61 0 0 0 125.82 69.59ZM113.98 57.46L134.58 36.86A11.67 11.67 0 0 0 118.09 20.37L97.49 40.97A11.67 11.67 0 0 0 113.98 57.46Z"
      />
      <g className="kn-sweep">
        <circle className="kern-thinking-body" cx="26.5" cy="128.45" r="7.07" />
        <circle
          className="kern-thinking-accent"
          cx="103.62"
          cy="51.33"
          r="7.07"
        />
      </g>
      <g className="kn-rest">
        <circle
          className="kern-thinking-body"
          cx="50.28"
          cy="104.78"
          r="7.07"
        />
        <circle
          className="kern-thinking-accent"
          cx="104.78"
          cy="50.28"
          r="7.07"
        />
      </g>
      <g clipPath="url(#kern-thinking-b)">
        <g transform="rotate(-45 38.92 116.04)">
          <rect
            className="kern-thinking-body"
            x="-31.08"
            y="46.35"
            width="140"
            height="60"
          />
        </g>
      </g>
      <g clipPath="url(#kern-thinking-a)">
        <g transform="rotate(-45 116.04 38.92)">
          <rect
            className="kern-thinking-accent"
            x="46.04"
            y="-30.77"
            width="140"
            height="60"
          />
        </g>
      </g>
      <g className="kn-trail">
        <circle
          className="kern-thinking-stroke"
          cx="120"
          cy="-8"
          r="3.2"
          fill="none"
          strokeWidth="3"
        />
        <circle
          className="kern-thinking-stroke"
          cx="126"
          cy="-18"
          r="5.2"
          fill="none"
          strokeWidth="3"
        />
      </g>
      <g transform="translate(129 -44)">
        <g className="kn-cloud">
          <path
            className="kern-thinking-stroke"
            d="M-20.19 11.94A11 11 0 0 1 -21.73 -9.66A13 13 0 0 1 -3.27 -18.67A13.5 13.5 0 0 1 17.73 -12.5A11.5 11.5 0 0 1 21.56 9.94A10 10 0 0 1 7.77 16.06A10.5 10.5 0 0 1 -6.74 17.05A10 10 0 0 1 -20.19 11.94Z"
            fill="none"
            strokeWidth="4.4"
            strokeLinejoin="round"
          />
          <g transform="translate(-12 0)">
            <circle className="kn-dot kn-d1 kern-thinking-accent" r="4.3" />
          </g>
          <g transform="translate(0 0)">
            <circle className="kn-dot kn-d2 kern-thinking-accent" r="4.3" />
          </g>
          <g transform="translate(12 0)">
            <circle className="kn-dot kn-d3 kern-thinking-accent" r="4.3" />
          </g>
        </g>
      </g>
    </svg>
  );
}
