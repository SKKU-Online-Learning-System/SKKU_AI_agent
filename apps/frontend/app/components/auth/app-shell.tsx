"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import {
  getGlobalNavItems,
  getRoleHomePath,
  getRoleMenuItems,
  roleLabels
} from "../../lib/auth";
import { UiIcon } from "../ui/ui-icon";
import { useAuth } from "./auth-provider";

function isActivePath(pathname: string, href: string, roleHomePath: string): boolean {
  return href === roleHomePath
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { logout, user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [isContextNavOpen, setIsContextNavOpen] = useState(true);
  const isCourseWorkspace =
    /^\/(student|professor)\/courses\/[^/]+/.test(pathname) ||
    /^\/admin\/course\/[^/]+/.test(pathname);

  if (!user) {
    return <main className="auth-status-page">사용자 정보를 불러오고 있습니다.</main>;
  }

  const menuItems = getRoleMenuItems(user.role);
  const globalItems = getGlobalNavItems(user.role);
  const roleHomePath = getRoleHomePath(user.role);
  const activeMenuItem = menuItems.find((item) => isActivePath(pathname, item.href, roleHomePath));
  const currentTitle = activeMenuItem?.label ?? roleLabels[user.role];

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

  return (
    <div className="icampus-app-shell" data-course-workspace={isCourseWorkspace}>
      <aside className="icampus-global-nav">
        <Link className="icampus-crest" href={roleHomePath}>
          {/* The supplied crest is a fixed-size local asset in the required shell markup. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="성균관대학교" src="/skku-logo-white.PNG" />
        </Link>
        <nav aria-label="i-Campus 전역 메뉴">
          {globalItems.map((item) =>
            item.href ? (
              <Link
                aria-current={
                  isActivePath(pathname, item.href, roleHomePath) ? "page" : undefined
                }
                href={item.href}
                key={item.label}
              >
                <UiIcon name={item.icon} />
                <span>{item.label}</span>
              </Link>
            ) : (
              <span key={item.label} title="이 MVP에서는 제공하지 않는 메뉴입니다.">
                <UiIcon name={item.icon} />
                <span>{item.label}</span>
              </span>
            )
          )}
        </nav>
      </aside>
      <div className="icampus-app-main">
        {/* Inside a course the workspace renders the same top bar with the
            course context, exactly like i-Campus does. */}
        {!isCourseWorkspace ? (
          <header className="icampus-app-topbar">
            <button
              aria-controls="icampus-context-navigation"
              aria-expanded={isContextNavOpen}
              aria-label={`보조 메뉴 ${isContextNavOpen ? "접기" : "열기"}`}
              className="icampus-menu-toggle"
              onClick={() => setIsContextNavOpen((isOpen) => !isOpen)}
              type="button"
            >
              <span aria-hidden="true">☰</span>
            </button>
            <strong>{currentTitle}</strong>
            <div className="icampus-user-menu">
              <span>
                {user.name} {roleLabels[user.role]}
              </span>
              <button type="button" onClick={handleLogout}>
                로그아웃
              </button>
            </div>
          </header>
        ) : null}
        <div className="icampus-app-body">
          {!isCourseWorkspace ? (
            <aside
              aria-label={`${roleLabels[user.role]} 보조 메뉴`}
              className="icampus-context-nav"
              data-open={isContextNavOpen}
              id="icampus-context-navigation"
            >
              <strong>{roleLabels[user.role]} 메뉴</strong>
              <nav aria-label={`${roleLabels[user.role]} 메뉴`}>
                {menuItems.map((item) => (
                  <Link
                    aria-current={
                      isActivePath(pathname, item.href, roleHomePath) ? "page" : undefined
                    }
                    href={item.href}
                    key={item.href}
                  >
                    <UiIcon name={item.icon} />
                    <span>{item.label}</span>
                  </Link>
                ))}
              </nav>
            </aside>
          ) : null}
          {isCourseWorkspace ? (
            <div className="icampus-app-content icampus-app-content--course">{children}</div>
          ) : (
            <main className="icampus-app-content">{children}</main>
          )}
        </div>
      </div>
    </div>
  );
}
