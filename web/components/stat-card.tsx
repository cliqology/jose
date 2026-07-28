type Props = {
  label: string;
  value: number;
  detail?: string;
  warning?: boolean;
};

export function StatCard({ label, value, detail, warning = false }: Props) {
  return (
    <article className={`statCard${warning ? " warning" : ""}`}>
      <p>{label}</p>
      <strong>{value.toLocaleString()}</strong>
      {detail ? <small>{detail}</small> : null}
    </article>
  );
}
