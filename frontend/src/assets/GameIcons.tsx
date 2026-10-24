interface IconProps {
  className?: string;
  size?: number;
}

export function ShieldIcon({ className = "", size = 40 }: IconProps) {
  return (
    <svg
      width={size}
      height={size * 1.2}
      viewBox="0 0 40 48"
      fill="none"
      className={className}
    >
      <path
        d="M20 2L4 10V24C4 34 12 42 20 46C28 42 36 34 36 24V10L20 2Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M20 6L8 12V24C8 32 14 38 20 42C26 38 32 32 32 24V12L20 6Z"
        stroke="currentColor"
        strokeWidth="0.5"
        strokeOpacity="0.4"
        strokeLinejoin="round"
      />
      <path
        d="M12 14L20 10L28 14"
        stroke="currentColor"
        strokeWidth="0.5"
        strokeOpacity="0.3"
        strokeLinecap="round"
      />
      <circle cx="20" cy="22" r="2" stroke="currentColor" strokeWidth="0.8" strokeOpacity="0.5" />
      <path
        d="M16 28H24"
        stroke="currentColor"
        strokeWidth="0.5"
        strokeOpacity="0.3"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function SwordIcon({ className = "", size = 40 }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      className={className}
    >
      <line
        x1="8"
        y1="32"
        x2="30"
        y2="10"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <path
        d="M28 8L32 4L36 8L32 12L28 8Z"
        stroke="currentColor"
        strokeWidth="1"
        strokeLinejoin="round"
      />
      <line
        x1="14"
        y1="22"
        x2="22"
        y2="26"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <line
        x1="32"
        y1="32"
        x2="10"
        y2="10"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <path
        d="M8 12L4 8L8 4L12 8L8 12Z"
        stroke="currentColor"
        strokeWidth="1"
        strokeLinejoin="round"
      />
      <line
        x1="18"
        y1="14"
        x2="26"
        y2="18"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function CrownIcon({ className = "", size = 40 }: IconProps) {
  return (
    <svg
      width={size}
      height={size * 0.75}
      viewBox="0 0 40 30"
      fill="none"
      className={className}
    >
      <path
        d="M4 24L8 8L14 16L20 4L26 16L32 8L36 24H4Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <line
        x1="4"
        y1="24"
        x2="36"
        y2="24"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <circle cx="8" cy="8" r="1.5" fill="currentColor" fillOpacity="0.6" />
      <circle cx="20" cy="4" r="2" fill="currentColor" fillOpacity="0.7" />
      <circle cx="32" cy="8" r="1.5" fill="currentColor" fillOpacity="0.6" />
      <path
        d="M6 26H34"
        stroke="currentColor"
        strokeWidth="0.8"
        strokeOpacity="0.3"
      />
      <circle cx="12" cy="20" r="1" fill="currentColor" fillOpacity="0.3" />
      <circle cx="20" cy="18" r="1" fill="currentColor" fillOpacity="0.3" />
      <circle cx="28" cy="20" r="1" fill="currentColor" fillOpacity="0.3" />
    </svg>
  );
}

export function EyeIcon({ className = "", size = 40 }: IconProps) {
  return (
    <svg
      width={size}
      height={size * 0.6}
      viewBox="0 0 40 24"
      fill="none"
      className={className}
    >
      <path
        d="M2 12C2 12 8 4 20 4C32 4 38 12 38 12C38 12 32 20 20 20C8 20 2 12 2 12Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <circle cx="20" cy="12" r="5" stroke="currentColor" strokeWidth="1.2" />
      <circle cx="20" cy="12" r="2" fill="currentColor" fillOpacity="0.7" />
      <path
        d="M6 6L4 4"
        stroke="currentColor"
        strokeWidth="0.6"
        strokeOpacity="0.4"
        strokeLinecap="round"
      />
      <path
        d="M34 6L36 4"
        stroke="currentColor"
        strokeWidth="0.6"
        strokeOpacity="0.4"
        strokeLinecap="round"
      />
      <path
        d="M20 2V4"
        stroke="currentColor"
        strokeWidth="0.6"
        strokeOpacity="0.4"
        strokeLinecap="round"
      />
      <path
        d="M12 12C12 12 15 9 20 9C25 9 28 12 28 12"
        stroke="currentColor"
        strokeWidth="0.5"
        strokeOpacity="0.25"
      />
    </svg>
  );
}

export function SealApprove({ className = "", size = 40 }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      className={className}
    >
      <circle cx="20" cy="20" r="16" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="20" cy="20" r="13" stroke="currentColor" strokeWidth="0.6" strokeOpacity="0.4" />
      {[0, 45, 90, 135, 180, 225, 270, 315].map((angle) => {
        const rad = (angle * Math.PI) / 180;
        const x1 = 20 + 14.5 * Math.cos(rad);
        const y1 = 20 + 14.5 * Math.sin(rad);
        const x2 = 20 + 17 * Math.cos(rad);
        const y2 = 20 + 17 * Math.sin(rad);
        return (
          <line
            key={angle}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            stroke="currentColor"
            strokeWidth="1.2"
            strokeOpacity="0.5"
          />
        );
      })}
      <path
        d="M13 20L18 25L27 16"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function SealReject({ className = "", size = 40 }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      className={className}
    >
      <circle
        cx="20"
        cy="20"
        r="16"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeDasharray="3 2"
      />
      <circle cx="20" cy="20" r="13" stroke="currentColor" strokeWidth="0.6" strokeOpacity="0.3" />
      <path
        d="M14 14L26 26"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path
        d="M26 14L14 26"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path
        d="M8 10L10 6"
        stroke="currentColor"
        strokeWidth="0.8"
        strokeOpacity="0.3"
        strokeLinecap="round"
      />
      <path
        d="M32 10L30 6"
        stroke="currentColor"
        strokeWidth="0.8"
        strokeOpacity="0.3"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function DaggerIcon({ className = "", size = 40 }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      className={className}
    >
      <path
        d="M20 4L22 18H18L20 4Z"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      <line
        x1="20"
        y1="4"
        x2="20"
        y2="8"
        stroke="currentColor"
        strokeWidth="0.5"
        strokeOpacity="0.4"
      />
      <path
        d="M14 18H26V20H14V18Z"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      <path
        d="M12 18L14 16"
        stroke="currentColor"
        strokeWidth="0.8"
        strokeLinecap="round"
      />
      <path
        d="M28 18L26 16"
        stroke="currentColor"
        strokeWidth="0.8"
        strokeLinecap="round"
      />
      <rect
        x="18"
        y="20"
        width="4"
        height="10"
        rx="1"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <line
        x1="19"
        y1="22"
        x2="19"
        y2="28"
        stroke="currentColor"
        strokeWidth="0.4"
        strokeOpacity="0.3"
      />
      <circle cx="20" cy="33" r="3" stroke="currentColor" strokeWidth="1" />
      <circle cx="20" cy="33" r="1" fill="currentColor" fillOpacity="0.4" />
    </svg>
  );
}

export function ScrollIcon({ className = "", size = 40 }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      className={className}
    >
      <path
        d="M10 6C10 4.5 11.5 3 13 3H30C31.5 3 33 4.5 33 6"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <rect
        x="10"
        y="6"
        width="23"
        height="28"
        rx="1"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <path
        d="M10 34C10 35.5 8.5 37 7 37C5.5 37 4 35.5 4 34V10C4 8.5 5.5 7 7 7C8.5 7 10 8.5 10 10"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <line
        x1="15"
        y1="13"
        x2="28"
        y2="13"
        stroke="currentColor"
        strokeWidth="0.6"
        strokeOpacity="0.4"
      />
      <line
        x1="15"
        y1="17"
        x2="26"
        y2="17"
        stroke="currentColor"
        strokeWidth="0.6"
        strokeOpacity="0.4"
      />
      <line
        x1="15"
        y1="21"
        x2="28"
        y2="21"
        stroke="currentColor"
        strokeWidth="0.6"
        strokeOpacity="0.4"
      />
      <line
        x1="15"
        y1="25"
        x2="22"
        y2="25"
        stroke="currentColor"
        strokeWidth="0.6"
        strokeOpacity="0.4"
      />
    </svg>
  );
}

export function PassToken({ className = "", size = 40 }: IconProps) {
  return (
    <svg
      width={size}
      height={size * 1.2}
      viewBox="0 0 40 48"
      fill="none"
      className={className}
    >
      <path
        d="M20 2L4 10V24C4 34 12 42 20 46C28 42 36 34 36 24V10L20 2Z"
        fill="#2e9e5b"
        fillOpacity="0.15"
        stroke="#2e9e5b"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M20 6L8 12V24C8 32 14 38 20 42C26 38 32 32 32 24V12L20 6Z"
        stroke="#2e9e5b"
        strokeWidth="0.5"
        strokeOpacity="0.3"
        strokeLinejoin="round"
      />
      <path
        d="M14 22L18 26L26 18"
        stroke="#4cc27e"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function FailToken({ className = "", size = 40 }: IconProps) {
  return (
    <svg
      width={size}
      height={size * 1.2}
      viewBox="0 0 40 48"
      fill="none"
      className={className}
    >
      <path
        d="M20 2L4 10V24C4 34 12 42 20 46C28 42 36 34 36 24V10L20 2Z"
        fill="#c42b2b"
        fillOpacity="0.15"
        stroke="#c42b2b"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M18 2L4 10V26C4 34 10 40 18 44"
        stroke="#c42b2b"
        strokeWidth="0.4"
        strokeOpacity="0.2"
        strokeLinejoin="round"
      />
      <path
        d="M15 18L25 28"
        stroke="#f06a6a"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M25 18L15 28"
        stroke="#f06a6a"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M20 34L18 38"
        stroke="#c42b2b"
        strokeWidth="1"
        strokeOpacity="0.4"
        strokeLinecap="round"
      />
      <path
        d="M20 34L22 38"
        stroke="#c42b2b"
        strokeWidth="1"
        strokeOpacity="0.4"
        strokeLinecap="round"
      />
    </svg>
  );
}
