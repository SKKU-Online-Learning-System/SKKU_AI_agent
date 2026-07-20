// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  accessTokenStorageKey,
  apiRequest,
  createAdminCourse,
  clearAccessToken,
  deleteCourseMaterial,
  listAdminCourses,
  listCourseMaterials,
  listCourses,
  loginRequest,
  saveAccessToken,
  uploadCourseMaterial
} from "./api";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("adds the stored bearer token to protected requests", async () => {
    saveAccessToken("stored-token");
    const fetchMock = vi.fn<typeof fetch>(async () =>
      Response.json({
        id: "user-1",
        name: "Student",
        email: "student@skku.edu",
        role: "student"
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/api/auth/me");

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(request.headers).get("Authorization")).toBe("Bearer stored-token");
  });

  it("does not attach auth to login requests and stores removable tokens", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      Response.json({
        access_token: "issued-token",
        token_type: "bearer",
        user: {
          id: "admin-1",
          name: "Admin",
          email: "admin@skku.edu",
          role: "admin"
        }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await loginRequest("admin@skku.edu", "password123");
    const request = fetchMock.mock.calls[0][1] as RequestInit;

    expect(response.access_token).toBe("issued-token");
    expect(new Headers(request.headers).get("Authorization")).toBeNull();
    saveAccessToken(response.access_token);
    expect(localStorage.getItem(accessTokenStorageKey)).toBe("issued-token");
    clearAccessToken();
    expect(localStorage.getItem(accessTokenStorageKey)).toBeNull();
  });

  it("builds admin course filter queries and JSON payloads", async () => {
    saveAccessToken("admin-token");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json([]))
      .mockResolvedValueOnce(
        Response.json({
          id: "course-1",
          name: "AI",
          semester: "2026-2",
          description: null,
          professorId: "professor-1",
          professorName: "Professor",
          isActive: true,
          studentAccessCount: 0,
          createdAt: "2026-07-20T00:00:00.000Z",
          updatedAt: "2026-07-20T00:00:00.000Z"
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    await listAdminCourses({
      isActive: true,
      keyword: "AI",
      professorId: "professor-1",
      semester: "2026-2"
    });
    await createAdminCourse({
      name: "AI",
      semester: "2026-2",
      description: null,
      professorId: "professor-1",
      isActive: true
    });

    expect(fetchMock.mock.calls[0][0]).toContain(
      "/api/admin/courses?semester=2026-2&is_active=true&professor_id=professor-1&keyword=AI"
    );
    expect(fetchMock.mock.calls[1][0]).toContain("/api/admin/courses");
    expect(fetchMock.mock.calls[1][1]?.method).toBe("POST");
    expect(fetchMock.mock.calls[1][1]?.body).toBe(
      JSON.stringify({
        name: "AI",
        semester: "2026-2",
        description: null,
        professorId: "professor-1",
        isActive: true
      })
    );
  });

  it("lists courses", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json([]));
    vi.stubGlobal("fetch", fetchMock);

    await listCourses();

    expect(fetchMock.mock.calls[0][0]).toContain("/api/courses");
    expect(fetchMock.mock.calls[0][1]?.method).toBeUndefined();
  });

  it("lists materials for a course", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json([]));
    vi.stubGlobal("fetch", fetchMock);

    await listCourseMaterials("course-1");

    expect(fetchMock.mock.calls[0][0]).toContain("/api/courses/course-1/materials");
    expect(fetchMock.mock.calls[0][1]?.method).toBeUndefined();
  });

  it("uploads a material with FormData without forcing JSON content type", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json({}));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["notes"], "week1.txt", { type: "text/plain" });

    await uploadCourseMaterial("course-1", file);

    const [, options] = fetchMock.mock.calls[0];
    expect(options?.method).toBe("POST");
    expect(options?.body).toBeInstanceOf(FormData);
    expect(new Headers(options?.headers).has("Content-Type")).toBe(false);
  });

  it("deletes a material from a course", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await deleteCourseMaterial("course-1", "material-1");

    expect(fetchMock.mock.calls[0][0]).toContain("/api/courses/course-1/materials/material-1");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("DELETE");
  });
});
