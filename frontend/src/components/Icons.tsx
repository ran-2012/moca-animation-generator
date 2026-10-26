import type { SVGProps } from 'react'

export interface IconProps {
  size?: number
  className?: string
}

type Props = IconProps

function svgProps({ size = 16, className }: Props): SVGProps<SVGSVGElement> {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.7,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    className,
    'aria-hidden': true,
  }
}

export function IconPlay(props: Props) {
  return (
    <svg {...svgProps(props)} fill="currentColor" stroke="none">
      <path d="M8 5.5v13l10-6.5z" />
    </svg>
  )
}

export function IconPause(props: Props) {
  return (
    <svg {...svgProps(props)} fill="currentColor" stroke="none">
      <rect x="7" y="5" width="3.6" height="14" rx="1.2" />
      <rect x="13.4" y="5" width="3.6" height="14" rx="1.2" />
    </svg>
  )
}

export function IconPlus(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

export function IconImport(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 15V3m0 0L7.5 7.5M12 3l4.5 4.5" />
      <path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" />
    </svg>
  )
}

export function IconLayers(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 3 3 7.8l9 4.8 9-4.8z" />
      <path d="m3 12.4 9 4.8 9-4.8M3 17l9 4.8L21 17" />
    </svg>
  )
}

export function IconWand(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M4 20 15 9" />
      <path d="M14.5 4.5 16 3l1.5 1.5L19 4l-.5 2 1.5 1.5-1.5 1.5.5 2-2-.5L16 12.5 15 10l-2-.5L14.5 8z" />
      <path d="M7 5v3M5.5 6.5h3" />
    </svg>
  )
}

export function IconBake(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 3c.8 2.8-.6 4.2-1.8 5.4C9 9.7 8 11 8 13a4 4 0 0 0 8 0c0-1.6-.6-2.8-1.4-4" />
      <path d="M12 21a7 7 0 0 0 7-7c0-2.4-1-4.3-2.2-6" />
      <path d="M12 21a7 7 0 0 1-7-7c0-2.4 1-4.3 2.2-6" />
    </svg>
  )
}

export function IconSave(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M5 4h10.2L20 8.8V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" />
      <path d="M8 4v5h7V4M8 15h8" />
    </svg>
  )
}

export function IconChevronRight(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="m9 5 7 7-7 7" />
    </svg>
  )
}

export function IconChevronDown(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="m5 9 7 7 7-7" />
    </svg>
  )
}

export function IconEye(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

export function IconEyeOff(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M4 4l16 16" />
      <path d="M9.9 5.8A10 10 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17.6 17.6 0 0 1-3.2 4M6.1 7.4A17.4 17.4 0 0 0 2.5 12S6 18.5 12 18.5c1 0 2-.2 2.8-.6" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </svg>
  )
}

export function IconCheck(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="m4.5 12.5 5 5L20 7" />
    </svg>
  )
}

export function IconX(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  )
}

export function IconZoomIn(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5M11 8v6M8 11h6" />
    </svg>
  )
}

export function IconZoomOut(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5M8 11h6" />
    </svg>
  )
}

export function IconFit(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
    </svg>
  )
}

export function IconLock(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <rect x="4" y="10" width="16" height="10" rx="1.5" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  )
}

export function IconMusic(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M9 18V6l11-2v12" />
      <circle cx="6.5" cy="18" r="2.5" />
      <circle cx="17.5" cy="16" r="2.5" />
    </svg>
  )
}

export function IconFilm(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4" />
    </svg>
  )
}

export function IconImage(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="8.5" cy="9.5" r="1.6" />
      <path d="m4 17 5-5 3.5 3.5L16 12l4 4" />
    </svg>
  )
}

export function IconSliders(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
      <circle cx="16" cy="7" r="2.2" />
      <circle cx="8" cy="17" r="2.2" />
    </svg>
  )
}

export function IconAlert(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 4 2.8 20h18.4z" />
      <path d="M12 10v4.5M12 17.5v.5" />
    </svg>
  )
}

export function IconSpinner(props: Props) {
  return (
    <svg {...svgProps(props)} className={`spin ${props.className ?? ''}`}>
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  )
}

export function IconRefresh(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M20 11a8 8 0 1 0-2.3 5.7" />
      <path d="M20 5v6h-6" />
    </svg>
  )
}

export function IconDownload(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 3v12m0 0 4.5-4.5M12 15l-4.5-4.5" />
      <path d="M4 17v2.5A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5V17" />
    </svg>
  )
}

export function IconGrid(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <rect x="4" y="4" width="6.5" height="6.5" rx="1" />
      <rect x="13.5" y="4" width="6.5" height="6.5" rx="1" />
      <rect x="4" y="13.5" width="6.5" height="6.5" rx="1" />
      <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1" />
    </svg>
  )
}

export function IconClock(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </svg>
  )
}

export function IconSparkles(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="m12 3 1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z" />
      <path d="M18.5 15.5 19.4 18l2.5.9-2.5.9-.9 2.5-.9-2.5-2.5-.9 2.5-.9z" />
    </svg>
  )
}

export function IconLayout(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9h18M9 9v11" />
    </svg>
  )
}

export function IconFolder(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.5h9A1.5 1.5 0 0 1 21 10v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18z" />
    </svg>
  )
}

export function IconTrash(props: Props) {
  return (
    <svg {...svgProps(props)}>
      <path d="M4 7h16M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7" />
      <path d="M6.5 7l.8 12A1.5 1.5 0 0 0 8.8 20.5h6.4a1.5 1.5 0 0 0 1.5-1.5l.8-12" />
      <path d="M10.5 11v6M13.5 11v6" />
    </svg>
  )
}
