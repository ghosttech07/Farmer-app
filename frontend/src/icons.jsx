// Inline stroke icons (24x24 grid), coloured via currentColor.
const Svg = ({ size = 18, children, ...p }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...p}>
    {children}
  </svg>
);


export const Sun = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4 12H2M22 12h-2M18.36 5.64l1.42-1.42M4.22 19.78l1.42-1.42M18.36 18.36l1.42 1.42M4.22 4.22l1.42 1.42" />
  </Svg>
);

export const Mic = (p) => (
  <Svg {...p}>
    <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" /><path d="M19 10v1a7 7 0 0 1-14 0v-1" />
    <path d="M12 18v4M8 22h8" />
  </Svg>
);

export const Back = (p) => <Svg {...p}><path d="M19 12H5" /><polyline points="12 19 5 12 12 5" /></Svg>;

export const Stop = (p) => (
  <svg viewBox="0 0 24 24" width={p.size || 18} height={p.size || 18} fill="currentColor" aria-hidden="true">
    <rect x="6" y="6" width="12" height="12" rx="2" />
  </svg>
);





export const Speaker = (p) => (
  <Svg {...p}>
    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
    <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07" />
  </Svg>
);

export const Thumb = (p) => (
  <Svg {...p}>
    <path d="M7 10v12" />
    <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H7a2 2 0 0 1-2-2v-8.5a2 2 0 0 1 .5-1.32L9.64 3a1 1 0 0 1 1.98.22Z" />
  </Svg>
);

export const Pencil = (p) => <Svg {...p}><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /></Svg>;

export const Phone = (p) => (
  <Svg {...p}>
    <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" />
  </Svg>
);

export const X = (p) => <Svg {...p}><path d="M18 6 6 18M6 6l12 12" /></Svg>;

export const Check = (p) => <Svg {...p}><polyline points="20 6 9 17 4 12" /></Svg>;

export const Help = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3" /><path d="M12 17h.01" /></Svg>
);

export const Keyboard = (p) => (
  <Svg {...p}>
    <rect x="2" y="5" width="20" height="14" rx="2" />
    <path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 13h.01M18 13h.01M8 16h8M10 13h4" />
  </Svg>
);

export const Alert = (p) => (
  <Svg {...p}><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" /></Svg>
);

// Translate glyph: a character and an "A" (change the answer's language)
export const Language = (p) => (
  <Svg {...p}>
    <path d="m5 8 6 6M4 14l6-6 2-3M2 5h12M7 2h1M22 22l-5-10-5 10M14 18h6" />
  </Svg>
);
