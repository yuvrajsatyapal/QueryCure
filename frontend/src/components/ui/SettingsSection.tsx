import { useId, type ReactNode } from "react";

/** Linear-style settings row (DESIGN_SYSTEM §5): a label and one-line description on the left,
 * the controls on the right; stacked on phones. A page section is a named region; inside a form
 * (`group`) it is a labelled group of fields instead. */
export function SettingsSection({
  title,
  description,
  children,
  group = false,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  group?: boolean;
}) {
  const id = useId();
  const Heading = group ? "h3" : "h2";
  return (
    <section
      {...(group ? { role: "group", "aria-labelledby": id } : { "aria-label": title })}
      className="grid min-w-0 grid-cols-1 gap-x-10 gap-y-3 border-t border-border py-6 first:border-t-0 first:pt-0 md:grid-cols-[15rem_minmax(0,1fr)]"
    >
      <div className="flex flex-col gap-1">
        <Heading id={id} className="text-sm font-semibold">
          {title}
        </Heading>
        {description ? <p className="text-sm text-muted">{description}</p> : null}
      </div>
      <div className="flex min-w-0 flex-col gap-3">{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, action }: { title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-5">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="max-w-2xl text-sm text-muted">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}
