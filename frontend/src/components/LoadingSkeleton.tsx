export function LoadingSkeleton({ label }: { label: string }) {
  return (
    <div className="app-skeleton" role="status" aria-label={label}>
      <div className="app-skeleton__line" />
      <div className="app-skeleton__card" />
      <div className="app-skeleton__card" />
      <p className="app-skeleton__label">{label}</p>
    </div>
  )
}
