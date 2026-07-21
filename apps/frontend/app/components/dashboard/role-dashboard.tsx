import Link from "next/link";
import type { IconName } from "../ui/ui-icon";
import { UiIcon } from "../ui/ui-icon";

export type DashboardAction = {
  description: string;
  href: string;
  icon: IconName;
  label: string;
};

export function RoleDashboard({
  actions,
  description,
  title
}: {
  actions: DashboardAction[];
  description: string;
  title: string;
}) {
  return (
    <section className="role-dashboard">
      <header>
        <h1>{title}</h1>
        <p>{description}</p>
      </header>
      <div className="role-dashboard-grid">
        {actions.map((action, index) => (
          <Link href={action.href} key={action.href}>
            <span className="role-dashboard-card-color" data-color={index % 4} />
            <span className="role-dashboard-card-body">
              <UiIcon name={action.icon} />
              <strong>{action.label}</strong>
              <small>{action.description}</small>
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
