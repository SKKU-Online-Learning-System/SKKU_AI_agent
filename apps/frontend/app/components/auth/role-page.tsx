type RolePageProps = {
  title: string;
  description: string;
  items?: string[];
};

export function RolePage({ title, description, items = [] }: RolePageProps) {
  return (
    <section className="role-page">
      <header>
        <h1>{title}</h1>
        <p>{description}</p>
      </header>
      {items.length > 0 ? (
        <div className="role-page-grid">
          {items.map((item) => (
            <article key={item}>
              <strong>{item}</strong>
              <span>준비 중</span>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
