"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getRoleHomePath, getRoleMenuItems, roleLabels } from "../../lib/auth";
import { useAuth } from "./auth-provider";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { logout, user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  if (!user) {
    return <main className="auth-status-page">사용자 정보를 불러오고 있습니다.</main>;
  }

  const menuItems = getRoleMenuItems(user.role);
  const roleHomePath = getRoleHomePath(user.role);

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

  return (
    <div className="app-shell">
      <aside className="app-sidebar" aria-label="역할별 메뉴">
        <Link className="app-brand" href={getRoleHomePath(user.role)}>
          SKKU Course Agent
        </Link>
        <nav>
          {menuItems.map((item) => {
            const active =
              item.href === roleHomePath
                ? pathname === item.href
                : pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link key={item.href} aria-current={active ? "page" : undefined} href={item.href}>
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="app-main">
        <header className="app-topbar">
          <div>
            <span>{user.name}</span>
            <strong>{roleLabels[user.role]}</strong>
          </div>
          <button type="button" onClick={handleLogout}>
            로그아웃
          </button>
        </header>
        <main className="app-content">{children}</main>
      </div>
    </div>
  );
}
