"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getRoleHomePath, getRoleMenuItems, roleLabels } from "../../lib/auth";
import { UiIcon } from "../ui/ui-icon";
import { useAuth } from "./auth-provider";

function isActivePath(pathname: string, href: string, roleHomePath: string): boolean {
  return href === roleHomePath
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The site shell: a white header with the SKKU mark and the role's menu as
 * tabs, the page below. A student's course page is a full-screen study view
 * with its own bar, so it is rendered bare.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const { logout, user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const isStudyPage = /^\/student\/courses\/[^/]+/.test(pathname);
  const isCourseWorkspace =
    /^\/professor\/courses\/[^/]+/.test(pathname) || /^\/admin\/course\/[^/]+/.test(pathname);

  if (!user) {
    return <main className="auth-status-page">사용자 정보를 불러오고 있습니다.</main>;
  }

  if (isStudyPage) {
    return <>{children}</>;
  }

  const menuItems = getRoleMenuItems(user.role);
  const roleHomePath = getRoleHomePath(user.role);

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

  return (
    <div className="skku-shell">
      <header className="skku-header">
        <div className="skku-header-inner">
          <Link className="skku-brand" href={roleHomePath}>
            {/* Fixed-size local crest. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img alt="성균관대학교" src="/skku-logo.svg" />
            <span>
              <strong>SKKU COURSE AGENT</strong>
              <small>성균관대학교 AI 학습 조교</small>
            </span>
          </Link>
          <nav aria-label={`${roleLabels[user.role]} 메뉴`}>
            {menuItems.map((item) => (
              <Link
                aria-current={isActivePath(pathname, item.href, roleHomePath) ? "page" : undefined}
                href={item.href}
                key={item.href}
              >
                <UiIcon name={item.icon} />
                <span>{item.label}</span>
              </Link>
            ))}
          </nav>
          <div className="skku-user">
            <span>
              {user.name}
              <b>{roleLabels[user.role]}</b>
            </span>
            <button onClick={handleLogout} type="button">
              로그아웃
            </button>
          </div>
        </div>
      </header>
      {isCourseWorkspace ? (
        <div className="skku-content skku-content--course">{children}</div>
      ) : (
        <main className="skku-content">{children}</main>
      )}
    </div>
  );
}
